
# -- Compensation Scraper Interface -- #

'''

Lightweight Python API for running aerospace compensation scrapes.
Delegates all heavy lifting to CompensationScraper in tools/.

Usage:

    from scraperInterface import scraper, df, exportPath

For CLI usage, run cli.py instead:

    python cli.py --sources bls h1b --output results.xlsx

Author: Sean Bowman
Date:   02/26/2026

'''

# Standard library imports
import os

os.system('cls') # if os.name == 'nt' else 'clear')

# Local imports
from tools.compensationScraper import CompensationScraper, ScraperConfig

defaultConfig = ScraperConfig()
scraper = CompensationScraper(defaultConfig)
df = scraper.runFullScrape()
exportPath = scraper.exportToExcel(df, 'compensationData.xlsx')
