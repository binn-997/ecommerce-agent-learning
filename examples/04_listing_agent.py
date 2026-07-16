"""Compatibility entrypoint for the complete three-node Listing Agent demo."""

import asyncio
import json

from amazon_ai_platform.listing_agent import demo


if __name__ == "__main__":
    result = asyncio.run(demo())
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
