# Zillow automation

`property_listing_gen.py` searches Zillow by ZIP through the Apify actor `maxcopell/zillow-zip-search` and writes a JSON array of `propertyUrl` values for a later detail step.

**Inputs:** ZIP codes and a result limit in the script or its CLI. **Outputs:** a JSON file of listing URLs in this folder.

**Local run** from this directory:

```bash
python property_listing_gen.py --zip-codes 08057
```

**Script Manager:** `property-listing-gen`. Dispatch it with [script_manager.yml](../../.github/workflows/script_manager.yml). There is no Zillow-specific workflow.

**Secrets:** `APIFY_API_KEY`. The actor is paid per result. Optional `MVLLC_LOGS_KEY`.

Longer guide: [documentation/scripts/property_listing_gen.md](../../documentation/scripts/property_listing_gen.md).
