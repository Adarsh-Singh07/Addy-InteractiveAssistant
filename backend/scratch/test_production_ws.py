import asyncio
import websockets
import json

async def test_model(model_name):
    url = f"wss://api.adarshsingh.in/ws/voice?character=addy&model={model_name}&voice=Aoede&engine=gemini_live"
    print(f"Testing model: {model_name}")
    try:
        async with websockets.connect(url) as ws:
            # 1st message is status
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print("  Initial msg:", msg)
            
            # Wait for next message to check if it throws an error
            try:
                msg2 = await asyncio.wait_for(ws.recv(), timeout=5)
                print("  Secondary msg:", msg2)
            except asyncio.TimeoutError:
                print("  No error received immediately. Connection seems stable!")
    except Exception as e:
        print("  Connection failed:", str(e))

async def main():
    for model in ["gemini-2.0-flash-exp", "gemini-2.5-flash", "gemini-2.0-flash-live-preview", "gemini-3.1-flash-live-preview"]:
        await test_model(model)
        print("-" * 40)

asyncio.run(main())
