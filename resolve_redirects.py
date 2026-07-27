import os
import sys
import argparse
import requests
import pymysql
import pandas as pd
from urllib.parse import urlparse, parse_qs, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def get_db_connection():
    mysql_host = os.getenv("MYSQL_HOST")
    mysql_port = os.getenv("MYSQL_PORT", "3306")
    try:
        mysql_port = int(mysql_port)
    except ValueError:
        mysql_port = 3306
    mysql_user = os.getenv("MYSQL_USER")
    mysql_pass = os.getenv("MYSQL_PASS")
    mysql_db = os.getenv("MYSQL_DB")

    if not all([mysql_host, mysql_user, mysql_pass, mysql_db]):
        raise ValueError(
            "Missing database configuration in environment (.env: MYSQL_HOST, MYSQL_USER, MYSQL_PASS, MYSQL_DB)"
        )

    return pymysql.connect(
        host=mysql_host,
        port=mysql_port,
        user=mysql_user,
        password=mysql_pass,
        database=mysql_db,
        autocommit=False
    )


def extract_full_url(final_url):
    """
    Extract clean full Google Shopping search URL from response URL or continue parameter.
    Prevents storing any 505, CAPTCHA, or google.com/sorry URLs.
    """
    if not final_url or not isinstance(final_url, str):
        return None

    # Case 1: Google sorry / CAPTCHA rate limit redirect
    if 'google.com/sorry' in final_url or '/sorry/index' in final_url:
        parsed = urlparse(final_url)
        qs = parse_qs(parsed.query)
        cont = qs.get('continue', [None])[0]
        if cont:
            decoded = unquote(cont)
            if decoded.startswith('http') and 'google.com/sorry' not in decoded and '/sorry/index' not in decoded:
                return decoded
        return None

    # Case 2: Unresolved share.google link
    if final_url.lower().startswith('https://share.google'):
        return None

    # Case 3: Generic CAPTCHA or access denied pages
    url_lower = final_url.lower()
    if 'captcha' in url_lower or 'accessdenied' in url_lower:
        return None

    # Case 4: Clean valid destination URL
    if final_url.startswith('http'):
        return final_url

    return None


def resolve_single_url(row_id, product_id, url, headers):
    if not isinstance(url, str) or not url.startswith('http'):
        return row_id, product_id, None, 0, False

    try:
        # Use stream=True so we don't download large file bodies.
        # Follow redirects to inspect final response.url and status_code.
        response = requests.get(url, headers=headers, timeout=15, allow_redirects=True, stream=True)
        status_code = response.status_code
        final_url = response.url
        response.close()

        # Reject HTTP server errors (e.g. 505, 500, 502, 503) if not containing a valid redirect
        if status_code >= 500 and not ('google.com/sorry' in final_url or '/sorry/index' in final_url):
            return row_id, product_id, None, status_code, False

        # Extract clean target full URL
        full_url = extract_full_url(final_url)
        if not full_url:
            return row_id, product_id, None, status_code, False

        return row_id, product_id, full_url, status_code, True
    except Exception:
        return row_id, product_id, None, 0, False


def process_db_chunk(conn, rows, max_workers, batch_size, headers):
    pending_updates = []
    total_updated = 0
    total_failed = 0

    futures = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for row in rows:
            row_id, product_id, url, _ = row
            future = executor.submit(resolve_single_url, row_id, product_id, url, headers)
            futures[future] = (row_id, product_id)

        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing Chunk", leave=False):
            row_id, product_id, final_url, status_code, success = future.result()
            if success and final_url:
                pending_updates.append((final_url, row_id))
            else:
                total_failed += 1

            if len(pending_updates) >= batch_size:
                try:
                    with conn.cursor() as cursor:
                        update_sql = """
                        UPDATE google_shopping_results
                        SET google_seller_page_full_url = %s
                        WHERE id = %s
                        """
                        cursor.executemany(update_sql, pending_updates)
                    conn.commit()
                    total_updated += len(pending_updates)
                    pending_updates.clear()
                except Exception as err:
                    conn.rollback()
                    print(f"\nError batch updating database: {err}")

    if pending_updates:
        try:
            with conn.cursor() as cursor:
                update_sql = """
                UPDATE google_shopping_results
                SET google_seller_page_full_url = %s
                WHERE id = %s
                """
                cursor.executemany(update_sql, pending_updates)
            conn.commit()
            total_updated += len(pending_updates)
            pending_updates.clear()
        except Exception as err:
            conn.rollback()
            print(f"\nError completing final DB batch update: {err}")

    return total_updated, total_failed


def process_db(max_workers, batch_size, chunk_size, total_limit, headers):
    print("Connecting to MySQL database...")
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return

    query_count = """
    SELECT COUNT(*)
    FROM google_shopping_results
    WHERE
        google_seller_page_url LIKE 'https://share.google%'
        AND (
            google_seller_page_full_url IS NULL 
            OR google_seller_page_full_url = ''
            OR google_seller_page_full_url LIKE '%google.com/sorry%'
            OR google_seller_page_full_url LIKE '%share.google%'
        );
    """
    try:
        with conn.cursor() as cursor:
            cursor.execute(query_count)
            total_pending = cursor.fetchone()[0]
    except Exception as e:
        print(f"Error counting pending records: {e}")
        conn.close()
        return

    print(f"Total pending share.google records in DB: {total_pending}")
    if total_pending == 0:
        print("No pending records to process.")
        conn.close()
        return

    chunk_num = 0
    overall_updated = 0
    overall_failed = 0

    try:
        while True:
            # Determine limit for this chunk
            fetch_limit = chunk_size
            if total_limit and (overall_updated + overall_failed + fetch_limit) > total_limit:
                fetch_limit = total_limit - (overall_updated + overall_failed)
                if fetch_limit <= 0:
                    print(f"Reached total limit of {total_limit} records requested.")
                    break

            with conn.cursor() as cursor:
                query = """
                SELECT
                    id,
                    product_id,
                    google_seller_page_url,
                    google_seller_page_full_url
                FROM google_shopping_results
                WHERE
                    google_seller_page_url LIKE 'https://share.google%%'
                    AND (
                        google_seller_page_full_url IS NULL 
                        OR google_seller_page_full_url = ''
                        OR google_seller_page_full_url LIKE '%%google.com/sorry%%'
                        OR google_seller_page_full_url LIKE '%%share.google%%'
                    )
                ORDER BY id ASC
                LIMIT %s;
                """
                cursor.execute(query, (fetch_limit,))
                rows = cursor.fetchall()

            if not rows:
                print("All pending records processed!")
                break

            chunk_num += 1
            print(f"\n--- Processing Chunk #{chunk_num} ({len(rows)} records) ---")

            updated, failed = process_db_chunk(conn, rows, max_workers, batch_size, headers)
            overall_updated += updated
            overall_failed += failed

            print(f"Chunk #{chunk_num} Summary: Updated = {updated}, Failed/Skipped = {failed}")

            if total_limit and (overall_updated + overall_failed) >= total_limit:
                print(f"Reached requested limit of {total_limit} records.")
                break

    except KeyboardInterrupt:
        print("\nInterrupted by user. Committing completed chunk progress...")
    finally:
        conn.close()

    print(f"\n==========================================")
    print(f"Finished DB Redirect Resolution!")
    print(f"Total Chunks Processed: {chunk_num}")
    print(f"Total Updated google_seller_page_full_url: {overall_updated}")
    print(f"Total Failed/Skipped (errors/captcha/505): {overall_failed}")
    print(f"==========================================")


def process_csv(csv_path, max_workers, chunk_size, headers):
    if not os.path.exists(csv_path):
        print(f"Error: CSV file '{csv_path}' not found.")
        return

    df = pd.read_csv(csv_path)
    if 'redirected_url' not in df.columns:
        df['redirected_url'] = None
    df['redirected_url'] = df['redirected_url'].astype(object)

    urls_to_process = df[
        df['redirected_url'].isna() |
        (df['redirected_url'].astype(str).str.strip() == "") |
        df['redirected_url'].astype(str).str.startswith("Error:") |
        df['redirected_url'].astype(str).str.contains("google.com/sorry")
    ]
    print(f"Total CSV rows: {len(df)}. Remaining to process: {len(urls_to_process)}")

    if len(urls_to_process) == 0:
        print("All CSV URLs resolved!")
        return

    indices = list(urls_to_process.index)
    total_chunks = (len(indices) + chunk_size - 1) // chunk_size

    for chunk_idx in range(total_chunks):
        chunk_indices = indices[chunk_idx * chunk_size : (chunk_idx + 1) * chunk_size]
        print(f"\n--- CSV Chunk {chunk_idx + 1}/{total_chunks} ({len(chunk_indices)} records) ---")

        futures = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for idx in chunk_indices:
                url = df.at[idx, 'url']
                future = executor.submit(resolve_single_url, idx, None, url, headers)
                futures[future] = idx

            for future in tqdm(as_completed(futures), total=len(futures), desc="Resolving CSV Chunk", leave=False):
                idx_res, _, final_url, status_code, success = future.result()
                if success and final_url:
                    df.at[idx_res, 'redirected_url'] = final_url

        temp_path = csv_path + '.tmp'
        df.to_csv(temp_path, index=False)
        os.replace(temp_path, csv_path)
        print(f"CSV Progress saved for Chunk {chunk_idx + 1}/{total_chunks}")

    print(f"\nCSV processing complete! Output saved to {csv_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Resolve Google seller page share URLs chunk-wise and save full URLs to database or CSV."
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Optional path to CSV file to process instead of MySQL database."
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help="Number of records to fetch and process per chunk (default: 500)."
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=15,
        help="Maximum concurrent HTTP worker threads per chunk (default: 15)."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Database update batch transaction size (default: 50)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max total records to process across all chunks."
    )

    args = parser.parse_args()

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }

    if args.csv:
        process_csv(args.csv, args.max_workers, args.chunk_size, headers)
    else:
        process_db(args.max_workers, args.batch_size, args.chunk_size, args.limit, headers)


if __name__ == '__main__':
    main()
