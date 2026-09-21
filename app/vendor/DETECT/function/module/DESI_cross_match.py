from function.database import CatalogueService


def _extract_targets_from_dataset(dataset) -> list[tuple]:
    """Extract targets from dataset dict or return as-is if already a list."""
    if isinstance(dataset, dict):
        if 'targets' in dataset:
            return dataset['targets']
        elif 'tns' in dataset and dataset['tns'] and 'targets' in dataset['tns']:
            return dataset['tns']['targets']
    elif isinstance(dataset, list):
        return dataset
    return []


def desi_cross_match(target_list, search_radius=30):
    """
    Cross match with DESI data in PostgreSQL.

    Args:
        target_list (list | dict): List of tuples (ra, dec, target_name) or dataset dict
        search_radius (float): Search radius in arcseconds

    Returns:
        dict: Dictionary mapping target_name to list of matched dictionaries
    """
    targets = _extract_targets_from_dataset(target_list)
    if not targets:
        print("[WARNING] No targets provided for DESI cross-match")
        return {}

    try:
        return CatalogueService.cross_match_catalog(
            target_list=targets,
            catalog_name="DESI",
            search_radius=search_radius,
        )
    except (ValueError, KeyError) as e:
        print(f"[ERROR] DESI cross match failed: {type(e).__name__} - {e}")
        return {}
    except Exception as e:
        print(f"[ERROR] Unexpected error in DESI cross match: {type(e).__name__} - {e}")
        return {}


if __name__ == "__main__":
    # Example usage
    targets = [
        (0.9370, -1.8993, "TEST_OBJECT_1"),
        (10.0, 10.0, "TEST_OBJECT_2")
    ]

    results = desi_cross_match(targets, search_radius=30)

    print(f"Cross-match completed for {len(results)} objects.")
    for name, matches in results.items():
        print(f"{name}: Found {len(matches)} matches within 30 arcseconds radius")
        print(matches)
