
# -- Compensation Scraper CLI -- #

'''

Command-line interface for the aerospace compensation scraper.

Usage:

    python cli.py
    python cli.py --sources bls h1b careerPages --output results.xlsx
    python cli.py --list-sources
    python cli.py --merge --output merged.xlsx

Author: Sean Bowman
Date:   02/26/2026

'''

# Standard library imports
import os
import sys
import argparse

# Third-party imports
import pandas as pd

# Ensure tools directory is importable
_appDir = os.path.dirname(os.path.abspath(__file__))
_toolsDir = os.path.join(_appDir, 'tools')
if _toolsDir not in sys.path:
    sys.path.insert(0, _toolsDir)

# Local imports
from tools.compensationScraper import CompensationScraper, ScraperConfig
from tools.auditUtils import loadMarketSurveyData, mergeScrapedData


# ---------------------------------------------------------------------- #
# -- CLI Helpers -- #
# ---------------------------------------------------------------------- #

def listAvailableSources() -> list:

    '''Return list of available data source metadata dicts.'''

    sources = []
    for key, meta in CompensationScraper.availableSources.items():
        sources.append({
            'key': key,
            'name': meta['name'],
            'description': meta['description'],
            'requiresKey': meta['requiresKey'],
            'tier': meta['tier'],
        })
    return sorted(sources, key=lambda s: s['tier'])


def mergeWithExistingSurvey(scrapedDf, deduplicateBy=None) -> pd.DataFrame:

    '''Merge scraped data with the existing Excel survey data.'''

    existingDf = loadMarketSurveyData()
    return mergeScrapedData(existingDf, scrapedDf, deduplicateBy=deduplicateBy)


# ---------------------------------------------------------------------- #
# -- Main -- #
# ---------------------------------------------------------------------- #

def main():

    '''

    Parse CLI arguments and run the appropriate scraper commands.

    '''

    parser = argparse.ArgumentParser(
        description='Aerospace Compensation Scraper - CLI Interface'
    )
    parser.add_argument(
        '--sources', nargs='*', default=None,
        help='Sources to scrape (default: all). Use --list-sources to see options.'
    )
    parser.add_argument(
        '--bls-key', default='', help='BLS API key'
    )
    parser.add_argument(
        '--fred-key', default='', help='FRED API key'
    )
    parser.add_argument(
        '--output', default=None, help='Output Excel file path'
    )
    parser.add_argument(
        '--merge', action='store_true', help='Merge with existing survey data'
    )
    parser.add_argument(
        '--no-cache', action='store_true', help='Force fresh scrape (ignore cache)'
    )
    parser.add_argument(
        '--list-sources', action='store_true', help='List available sources and exit'
    )

    args = parser.parse_args()

    if args.list_sources:
        print('\nAvailable Data Sources:')
        print('-' * 60)
        for source in listAvailableSources():
            keyReq = ' (requires API key)' if source['requiresKey'] else ''
            print(f'  [{source["key"]}] {source["name"]}{keyReq}')
            print(f'    Tier {source["tier"]}: {source["description"]}')
        print()
        sys.exit(0)

    def printProgress(step, total, message):
        '''Print progress to console.'''
        pct = int((step / max(total, 1)) * 100)
        print(f'  [{pct:3d}%] {message}')

    print('\nAerospace Compensation Scraper')
    print('=' * 40)

    cacheTtl = 0 if args.no_cache else 168

    config = ScraperConfig(
        blsApiKey=args.bls_key,
        fredApiKey=args.fred_key,
        cacheTtlHours=cacheTtl,
    )
    scraper = CompensationScraper(config)
    result = scraper.runFullScrape(sources=args.sources, progressCallback=printProgress)

    print(f'\nCollected {len(result)} records')

    if not result.empty:
        # Show summary by source
        print('\nRecords by source:')
        if 'DataSource' in result.columns:
            for source, count in result['DataSource'].value_counts().items():
                print(f'  {source}: {count}')

        # Show salary summary
        minCol = pd.to_numeric(result['Min'], errors='coerce')
        maxCol = pd.to_numeric(result['Max'], errors='coerce')
        midpoints = (minCol + maxCol) / 2
        validMidpoints = midpoints.dropna()
        if not validMidpoints.empty:
            print(f'\nSalary range: ${validMidpoints.min():,.0f} - ${validMidpoints.max():,.0f}')
            print(f'Average midpoint: ${validMidpoints.mean():,.0f}')

    if args.merge:
        print('\nMerging with existing survey data...')
        result = mergeWithExistingSurvey(result)
        print(f'Total records after merge: {len(result)}')

    if args.output:
        outputPath = scraper.exportToExcel(result, args.output)
        print(f'\nExported to: {outputPath}')

    print('\nDone.')


if __name__ == '__main__':
    main()
