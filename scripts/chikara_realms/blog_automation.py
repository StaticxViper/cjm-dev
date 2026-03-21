import json
import sys
from pathlib import Path

# Add repo root to sys.path
repo_root = Path(__file__).resolve().parents[2]  # stock_analyzer.py -> stock_analyzer/ -> scripts/ -> repo_root
sys.path.insert(0, str(repo_root))

from openai import OpenAI
from shared.api_manager import APIManager as api
from shared.logger import setup_logger

logger = setup_logger(
    name="blog-automation",
    console_levels=["ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)

def topic_gen(category, gpt):
    """ Checks if topics exist within corresponding _topics.json file, if none, use API Manager to generate new topics """

    logger.critical(f'Checking Topic File: {category}_topics.json')
    try:
        with open(f"{category}_topics.json", "r") as file:
            content = json.loads(file.read())
    except (FileNotFoundError, json.JSONDecodeError):
        content = {"topics": []}
    
    if not content.get('topics', []):
        # Gen new topics, take the first one and save the rest to JSON file
        # Need to see output of ChatGPT response, and put into a list to load back into JSON file
        # Also need to pop the first topic before loading
        # topic = response_json[response?][0]
        logger.info(f'Topic file empty... Generating new topics based on " {category} "')

        response = gpt.chat.completions.create(
        model="gpt-4",
        messages=[
                {
                    "role": "system",
                    "content": "You generate structured JSON only."
                },
                {
                    "role": "user",
                    "content": f"""Generate 60 unique blog post titles for the category: "{category}".
                        Return ONLY valid JSON in this format:
                    {{"topics": [
                            "Title 1", 
                            "Title 2"]
                    }}"""
                }])

        response_content = response.choices[0].message.content
        data = json.loads(response_content)
        topics = data["topics"]
        topic = topics.pop(0)
        with open(f"{category}_topics.json", "w") as file:
            json.dump({"topics": topics}, file, indent=2)
    else:
        # Grab next topic
        topics = content["topics"]
        topic = topics.pop(0)
        with open(f"{category}_topics.json", "w") as file:
            json.dump({"topics": topics}, file, indent=2)
    
    return topic

def main():
    logger.critical('Starting Blog Automation...')
    base_url = 'https://rrtenkufprduezfurtwk.supabase.co/functions/v1'
    blog_endpoint = '/manage-blog'
    category_topics = {} # {"Sub-Catergory1": "Topic1", "Sub-Catergory2": "Topic2"}

    chatgpt_client = OpenAI(api_key=api().get_api_key(api='ChatGPT'))
    perplexity_url = 'https://api.perplexity.ai'

    # Gather Categories
    logger.critical("Gathering Categories...")
    with open("blog_category.json", 'r') as file:
        content = json.loads(file.read())

        # Extract list of sub-categories from each parent
        for _,sub_cat in content["Category"].items():
            #logger.critical(f"PARENT: {parent_cat}, SUB: {sub_cat}") #test
            for category in sub_cat: # sub_cat = list of catergories, ex. sub_cat = ["Catergory 1", "Category 2", "Category 3"]
                # Open topic file and add category and first topic to category_topics dict
                topic = topic_gen(category=category, gpt=chatgpt_client)
                logger.critical(f'Topic Acquired: "{topic}"')
    
    # Generate blog post based on topic + category
    perplexity_request = { "model": "sonar-pro",
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a professional SEO blog writer. Output strictly valid JSON only."
                            },
                            {
                                "role": "user",
                                "content": f"""Write a high-quality blog post for the topic: "{topic}".

                    Return ONLY JSON:
                    {
                    "title": "",
                    "slug": "",
                    "excerpt": "",
                    "content": "",
                    "tags": []
                    }

                    Rules:
                    - 1000+ words
                    - SEO optimized
                    - Use markdown headings (##, ###)
                    - No citations
                    - No extra commentary
                    - Clean formatting
                    - Beginner-friendly but insightful"""
                            }
                        ]
                    }
    perplexity_response = api().build_request(base_url=perplexity_url, endpoint='/chat/completions', json_body=perplexity_request, api="Perplexity")
    logger.info(f'Perplexity AI Response: " {perplexity_response} "')
    # Generate image thumbnail for blog post
    subject = f"""Visualize the concept of: {topic}.
        Represent this with a symbolic anime-style scene or character that clearly reflects the topic. 
        Use metaphors, environment, and subtle visual storytelling to convey the idea."""
    with open('img_prompt.txt', 'r') as prompt_file:
        chatgpt_prompt = prompt_file.read()
        prompt_file.close()
    
    result = chatgpt_client.images.generate(
        model="dall-e-3",
        prompt=chatgpt_prompt + subject,
        size="1024x1024"
    )

    # Extract image URL
    image_url = result.data[0].url
    logger.critical(f"Image generated. URL: {image_url}")

    # Send to Chikara
    # NOTE : Need to test if posts need to be sent 1 by 1, or if they can be sent in bulk ...
    # Also need JSON structure to be sent
    #api().build_request(base_url=base_url, endpoint=blog_endpoint, json_body=blog_post_data, api="Chikara Realms")

if __name__ == "__main__":
    main()
