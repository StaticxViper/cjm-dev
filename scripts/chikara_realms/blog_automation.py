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
        for parent_cat,sub_cat in content["Category"].items():
            #logger.critical(f"PARENT: {parent_cat}, SUB: {sub_cat}") #test
            for category in sub_cat:
                # Open topic file and add category and first topic to category_topics dict
                with open(f"{category}_topics.json", "r") as topic_file:
                    topic_contents = json.loads(topic_file.read())
                    category_topics[category] = topic_contents['Topic'][0]
    
    #logger.critical(f"TEST: {category_topics}") #test
    
    # Generate blog post based on topic + category
    chatgpt_request = ''
    chatgpt_response = api().build_request(base_url=chatgpt_url, json_body=chatgpt_request, api="ChatGPT")

    # Generate image thumbnail for blog post
    perplexity_request = ''
    perplexity_response = api().build_request(base_url=perplexity_url, json_body=perplexity_request, api="Perplexity")

    # Send to Chikara
    # NOTE : Need to test if posts need to be sent 1 by 1, or if they can be sent in bulk ...
    #api().build_request(base_url=base_url, endpoint=blog_endpoint, json_body=blog_post_data, api="Chikara Realms")


if __name__ == "__main__":
    main()
