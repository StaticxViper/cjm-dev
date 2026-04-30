import json

from openai import OpenAI
from perplexity import Perplexity
from helper_scripts.api_manager import APIManager as api
from helper_scripts.utilities.logger import setup_logger

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
    perplexity_client = Perplexity(api_key=api().get_api_key(api='Perplexity'))
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
                perplexity_request = {"model": "sonar-pro",
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a professional SEO blog writer. Output clean, well-formatted markdown text only."
                        },
                        {
                            "role": "user",
                            "content": f"""Research and write a compelling, thoughtful article about "{topic}" for Chikara Realms. 
                                The article should be clear, insightful, and subtly empowering, with a calm, 
                                reflective tone that invites readers to think deeper about the topic. 
                                Include practical takeaways where relevant, but avoid hype or exaggerated claims. 
                                Write in a style that feels timeless and stoic, 
                                appealing to readers who value depth, clarity, and subtle strength.
                                Use concise paragraphs, clear headings (H2 and H3 if needed), and short, impactful sentences. 
                                Remove any filler or repetitive phrases. If there are any factual claims, keep them clear and neutral.

                                Requirements:
                                - 1000+ words
                                - SEO optimized
                                - Beginner-friendly but insightful
                                - Use markdown formatting:
                                - Title as a single # heading
                                - Sections with ## and ###
                                - Use bullet points where appropriate, and be sure to use proper spacing for readability.
                                - Include:
                                - An introduction
                                - Well-structured sections
                                - A conclusion

                                Return only the blog post content in markdown format.
                            """
                        }
                    ]
                }
                perplexity_response = perplexity_client.chat.completions.create(
                    model=perplexity_request["model"],
                    messages=perplexity_request["messages"]
                )

                # Generate image thumbnail for blog post
                subject = f"""Visualize the concept of "{topic}" in relation to "{category}".
                    Represent this with a symbolic anime-style scene or character that clearly reflects the topic. 
                    Use metaphors, environment, and subtle visual storytelling to convey the idea."""
                with open('img_prompt.txt', 'r') as prompt_file:
                    chatgpt_prompt = prompt_file.read()
                    prompt_file.close()
                
                result = chatgpt_client.images.generate(
                    model="dall-e-3",
                    prompt=chatgpt_prompt + subject,
                    size="1792x1024",
                )

                # Extract image URL
                image_url = result.data[0].url
                logger.critical(f"Image generated. URL: {image_url}")

                # Send to Chikara
                # NOTE : Need to test if posts need to be sent 1 by 1, or if they can be sent in bulk ...
                # Categories are not added currently. Need to figure out on frontend.
                blog_post_data = {"title": f"{topic}",
                                "slug": f"{topic.replace(' ', '-').lower()}",
                                "excerpt": f"Learn about {topic} in this comprehensive blog post.",
                                "content": f"{perplexity_response.choices[0].message.content}",
                                "featured_image": f"{image_url}",
                                "categories": [
                                    f"{category}"
                                ],
                                "citations": [citation for citation in perplexity_response.citations],
                                "publish": True
                                }
                test_blog_post_data = {"title": "Test Post",
                                "slug": "test-post",
                                "excerpt": "This is a test post.",
                                "content": f"{perplexity_response.choices[0].message.content}",
                                "featured_image": "https://design.google/library/evolving-google-identity",
                                "categories": [
                                    "discipline"
                                ],
                                "citations": [citation for citation in perplexity_response.citations],
                                "publish": False
                                }
                logger.critical(f"Blog Post Data: {test_blog_post_data}")

                api().build_request(base_url=base_url, endpoint=blog_endpoint, json_body=blog_post_data, api="Chikara Realms", method="POST", timeout=60.0)

if __name__ == "__main__":
    main()
