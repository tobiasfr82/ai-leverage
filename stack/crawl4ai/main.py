import asyncio
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

async def clean_ig_crawl():
    # 1. Define the Filter: This removes scripts, navs, and footers automatically
    prune_filter = PruningContentFilter(
        threshold=0.45,       # Higher = more aggressive pruning
        min_word_threshold=15 # Ignore small text blocks like "Click here"
    )

    md_generator = DefaultMarkdownGenerator(content_filter=prune_filter)

    # 2. Browser Config (Keep your stealth settings!)
    browser_cfg = BrowserConfig(
        headless=True,
        enable_stealth=True
    )

    # 3. Run Config: Tell it to generate "fit_markdown"
    # This is the secret sauce to stop seeing <iframe> and <script> tags.
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        markdown_generator=md_generator,
        word_count_threshold=20, # Don't bother with tiny snippets
        excluded_tags=['script', 'style', 'noscript', 'nav', 'footer', 'header']
    )

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        print("🔍 Crawling IG Labs with Noise Cancellation...")
        result = await crawler.arun(
            url="https://labs.ig.com/rest-trading-api-reference",
            config=run_cfg
        )

        if result.success:
            # result.markdown is the standard clean version
            # result.fit_markdown is the ultra-clean version filtered by our prune_filter
            clean_text = result.fit_markdown or result.markdown
            
            print("\n--- CLEAN DATA PREVIEW ---")
            print(clean_text[:1000]) # You should see readable API docs now!
            
            with open("ig_docs_clean.md", "w", encoding="utf-8") as f:
                f.write(clean_text)
        else:
            print(f"Error: {result.error_message}")

if __name__ == "__main__":
    asyncio.run(clean_ig_crawl())