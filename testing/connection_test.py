import asyncio # Python livrary for handling many things at once without
               # using threads

import websockets #Python websocket library

# --- This code goes on the Raspberry Pi ---

# The purpose of this script is to prove that the Websocket network 
# path for  controls works from the Meta Quest to the router to the
# Raspberry Pi Car and back.

# async def' marks a function that can pause and resume.
async def handler(ws):
    # loops over messages as they arrive, pausing in between,
    # exits by itself when the client disconnects
    async for msg in ws:
        print("got:", msg)
        await ws.send("ack: " + msg) # send a reply and wait

async def main():

    # starts the server:
    # args:
    # - handler: run for each client that connects
    # - "0.0.0.0": network interface to listen on (all of them)
    # - 8765: port number (make sure the port searched for in the
    #         browser matches)

    # * 'async with': means "set this up, run the indented block, shut
    #                 the serverr down cleanly when the block ends even
    #                 if something crashed"
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("listening on 8765")
        await asyncio.Future() # makes it such that the server runs until
                               # ctrl + c is pressed
# starts the async machinery, runs main until it finishes,
# then brings everything down when ctrl + c is pressed
asyncio.run(main())