#!/usr/bin/env python3
"""Tool to insert test gifwords into the database for testing"""

import asyncio
import logging
import sys

import nowplaying.bootstrap
import nowplaying.config
import nowplaying.trackrequests
import nowplaying.types


async def add_test_gifwords(keywords: str = "test", requester: str = "test-tool"):
    """Add a test gifwords entry using the proper trackrequests flow"""

    # Initialize using proper bootstrap
    nowplaying.bootstrap.set_qt_names()
    config = nowplaying.config.ConfigFile()
    requests_handler = nowplaying.trackrequests.Requests(config)

    print(f"Creating test gifwords request for: '{keywords}'")

    try:
        # Create a dummy setting for gifwords requests
        setting: nowplaying.types.UserTrackRequest = {
            "type": "GifWords",
        }

        # Use the proper gifwords_request method which will:
        # 1. Search for the GIF using the keywords
        # 2. Download the image
        # 3. Add to the database
        result = await requests_handler.gifwords_request(setting, requester, keywords)

        if result and result.get("image"):
            print(f"Successfully created gifwords request: '{keywords}' from {requester}")
            print(f"Image size: {len(result['image'])} bytes")
            return True
        print("No image found or gifwords request failed")
        return False

    except Exception as err:  # pylint: disable=broad-exception-caught
        print(f"Error: {err}")
        return False


def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python test_gifwords.py <keywords> [requester]")
        print("Example: python test_gifwords.py 'dancing cat' 'testuser'")
        print("Example: python test_gifwords.py 'excited' 'testuser'")
        sys.exit(1)

    keywords = sys.argv[1]
    requester = sys.argv[2] if len(sys.argv) > 2 else "test-tool"

    print("Creating test gifwords request:")
    print(f"  Keywords: {keywords}")
    print(f"  Requester: {requester}")
    print()

    if asyncio.run(add_test_gifwords(keywords, requester)):
        print("\n✅ Test gifwords added successfully!")
        print("The gifwords should now appear in any connected WebSocket sessions.")
    else:
        print("\n❌ Failed to add test gifwords.")
        sys.exit(1)


if __name__ == "__main__":
    # Set up basic logging
    logging.basicConfig(level=logging.INFO)
    main()
