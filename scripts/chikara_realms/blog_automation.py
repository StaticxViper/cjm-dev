import json
import sys
from pathlib import Path

# Add repo root to sys.path
repo_root = Path(__file__).resolve().parents[2]  # stock_analyzer.py -> stock_analyzer/ -> scripts/ -> repo_root
sys.path.insert(0, str(repo_root))

from shared.api_manager import APIManager as api
from shared.logger import setup_logger

logger = setup_logger(
    name="blog-automation",
    console_levels=["ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)

def topic_gen(category, gpt_url):
    """ Checks if topics exist within corresponding _topics.json file, if none, use API Manager to generate new topics """

    logger.critical(f'Checking Topic File: {category}_topics.json')
    with open(f"{category}_topics.json", "r") as file:
        content = json.loads(file.read())
        file.close()
    if content['Topic'][0] is None:
        # Gen new topics, take the first one and save the rest to JSON file
        request = ''
        chatgpt_response = api().build_request(base_url=gpt_url, json_body=request, api="ChatGPT")
        response_json = json.loads(chatgpt_response)
        # Need to see output of ChatGPT response, and put into a list to load back into JSON file
        # Also need to pop the first topic before loading
        # topic = response_json[response?][0]
        with open(f"{category}_topics.json", "w") as file:
            new_content = json.loads(file.read())


            json.dump(new_content)

    else:
        # Grab next topic
        topic = content['Topic'][0]
    
    return topic


def main():
    logger.critical('Starting Blog Automation...')
    base_url = 'https://rrtenkufprduezfurtwk.supabase.co/functions/v1'
    blog_endpoint = '/manage-blog'
    category_topics = {} # {"Sub-Catergory1": "Topic1", "Sub-Catergory2": "Topic2"}

    chatgpt_url = ''
    perplexity_url = ''

    # Gather Categories
    logger.critical("Gathering Categories...")
    with open("blog_category.json", 'r') as file:
        content = json.loads(file.read())

        # Extract list of sub-categories from each parent
        for _,sub_cat in content["Category"].items():
            #logger.critical(f"PARENT: {parent_cat}, SUB: {sub_cat}") #test
            for category in sub_cat: # sub_cat = list of catergories, ex. sub_cat = ["Catergory 1", "Category 2", "Category 3"]
                # Open topic file and add category and first topic to category_topics dict
                topic = topic_gen(category=category, gpt_url=chatgpt_url)

    #logger.critical(f"TEST: {category_topics}") #test
    
    # Generate blog post based on topic + category
    perplexity_request = ''
    perplexity_response = api().build_request(base_url=perplexity_url, json_body=perplexity_request, api="Perplexity")

    # Generate image thumbnail for blog post
    chatgpt_request = ''
    chatgpt_response = api().build_request(base_url=chatgpt_url, json_body=chatgpt_request, api="ChatGPT")

    # Send to Chikara
    # NOTE : Need to test if posts need to be sent 1 by 1, or if they can be sent in bulk ...
    #api().build_request(base_url=base_url, endpoint=blog_endpoint, json_body=blog_post_data, api="Chikara Realms")


if __name__ == "__main__":
    main()
