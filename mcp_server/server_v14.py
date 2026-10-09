"""Opt-in Direct v3 routing layer; delegates all legacy routes unchanged."""
import asyncio
from . import server_v13 as legacy
from . import direct_v3_http as direct

async def app(scope,receive,send):
    if scope.get("type")=="lifespan":
        task=None
        while True:
            msg=await receive()
            if msg["type"]=="lifespan.startup":
                task=asyncio.create_task(direct.periodic_reconcile())
                await send({"type":"lifespan.startup.complete"})
            elif msg["type"]=="lifespan.shutdown":
                if task:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                await send({"type":"lifespan.shutdown.complete"})
                return
    elif scope.get("type")=="http" and str(scope.get("path","")).startswith(direct.PREFIX+"/"):
        return await direct.handle(scope,receive,send)
    return await legacy.app(scope,receive,send)

mcp=legacy.mcp
