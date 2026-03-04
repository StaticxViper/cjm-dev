import httpx

class APIManager:

    def __init__(self, url=None):
        self.default_url = 'https://httpbin.org'
        if url == None:
            url = self.default_url
        
        r = httpx.get(url)
        print(r)






if __name__ == "__main__":
    instance = APIManager()
