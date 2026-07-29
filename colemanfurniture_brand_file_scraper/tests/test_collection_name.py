import sys
import os
from pathlib import Path

# Add project directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fetcher.product_fetcher import ProductFetcher

class DummyLogger:
    def error(self, msg, *args, **kwargs):
        print(f"ERROR: {msg}")
    def info(self, msg, *args, **kwargs):
        print(f"INFO: {msg}")
    def debug(self, msg, *args, **kwargs):
        print(f"DEBUG: {msg}")

class DummyFetcher(ProductFetcher):
    @property
    def logger(self):
        return DummyLogger()
        
    def __init__(self):
        pass

def test_extract_collection_name():
    fetcher = DummyFetcher()
    
    # Test case 1: exact pattern "Part Of [Collection Name] Collection From [Brand]"
    content_1 = {
        "accordion": {
            "productDetail": {
                "items": [
                    "Part Of Foley design Collection From Jackson, Left-arm (LAF)..."
                ]
            }
        }
    }
    brand_1 = "Jackson"
    res_1 = fetcher.extract_collection_name(content_1, brand_1)
    print(f"Test 1: Input='{content_1['accordion']['productDetail']['items'][0]}', Brand='{brand_1}' -> Extracted='{res_1}'")
    assert res_1 == "Foley design Collection", f"Expected 'Foley design Collection', got '{res_1}'"

    # Test case 2: "Part of [Collection] From [Brand]" (no "Collection" in middle, should append it)
    content_2 = {
        "accordion": {
            "productDetail": {
                "items": [
                    "Part Of Foley design From Jackson"
                ]
            }
        }
    }
    brand_2 = "Jackson"
    res_2 = fetcher.extract_collection_name(content_2, brand_2)
    print(f"Test 2: Input='{content_2['accordion']['productDetail']['items'][0]}', Brand='{brand_2}' -> Extracted='{res_2}'")
    assert res_2 == "Foley design Collection", f"Expected 'Foley design Collection', got '{res_2}'"

    # Test case 3: "Part of [Collection] Collection From [Brand]" inside a dict item
    content_3 = {
        "accordion": {
            "productDetail": {
                "items": [
                    {"content": "Part Of Rockport Gray Collection From Ashley, recliner..."}
                ]
            }
        }
    }
    brand_3 = "Ashley"
    res_3 = fetcher.extract_collection_name(content_3, brand_3)
    print(f"Test 3: Input='{content_3['accordion']['productDetail']['items'][0]['content']}', Brand='{brand_3}' -> Extracted='{res_3}'")
    assert res_3 == "Rockport Gray Collection", f"Expected 'Rockport Gray Collection', got '{res_3}'"

    # Test case 4: features -> items nested structure
    content_4 = {
        "accordion": {
            "productDetail": {
                "features": {
                    "items": [
                        "Part Of Foley Collection From Jackson",
                        "Lead finish"
                    ]
                }
            }
        }
    }
    brand_4 = "Jackson"
    res_4 = fetcher.extract_collection_name(content_4, brand_4)
    print(f"Test 4: features->items, Brand='{brand_4}' -> Extracted='{res_4}'")
    assert res_4 == "Foley Collection", f"Expected 'Foley Collection', got '{res_4}'"

    # Test case 5: "part of" is not the first item in the items list
    content_5 = {
        "accordion": {
            "productDetail": {
                "features": {
                    "items": [
                        "Fabric Content: 100% Polyester",
                        "Part Of Rockport Collection From Ashley",
                        "Lead finish"
                    ]
                }
            }
        }
    }
    brand_5 = "Ashley"
    res_5 = fetcher.extract_collection_name(content_5, brand_5)
    print(f"Test 5: 'part of' in middle of list, Brand='{brand_5}' -> Extracted='{res_5}'")
    assert res_5 == "Rockport Collection", f"Expected 'Rockport Collection', got '{res_5}'"

    # Test case 6: no matching accordion items
    content_6 = {}
    res_6 = fetcher.extract_collection_name(content_6, "Ashley")
    assert res_6 == "", f"Expected '', got '{res_6}'"

    print("All tests passed successfully!")

if __name__ == "__main__":
    test_extract_collection_name()
