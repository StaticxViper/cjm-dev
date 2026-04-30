from dotenv import load_dotenv
from httpx import request
from helper_scripts.api_manager import api_manager
from helper_scripts.utilities.logger import setup_logger

load_dotenv()


logger = setup_logger(
    name="api-manager",
    console_levels=["INFO", "ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)

def extract_property_data(objective:str = None, data:dict = None):
    """ Iterate through property data and extract specific data based on objective. """

    # TODO: Add additional objectives based on input from user. 
    # Objective Ideas: General Info, Agent Info, Financial Info, etc.


    




def main():

    api = api_manager.APIManager()

    logger.critical(f'Input a Property Address:\n')
    address = input()

    logger.info('Address submitted ... \n')
    logger.info(f'Extracting Property data from: " {address} "\n')

    # TODO: Add logic to get multiple listings at once.
    input_data = {
        "addresses": [str(address)]
    }
    listing_data = api.run_apify(actor='Zillow Detail Scraper', input=input_data)

    logger.debug(f'LISTING DATA: {listing_data}')

    if len(listing_data) == 1:
        output_data = extract_property_data(data=listing_data[0])
    #else:
        # TODO

    logger.critical(f'OUTPUT DATA:\n {output_data}')





if __name__ == "__main__":
    main()