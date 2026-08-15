"""
Script to inject cache invalidation into menu.py
"""

helper_code = """

async def invalidate_menu_cache(restaurant_id: int, db: AsyncSession):
    import redis.asyncio as redis_async
    from app.core.config import settings
    from app.models import Restaurant
    
    if not settings.REDIS_URL:
        return
        
    try:
        r = redis_async.from_url(settings.REDIS_URL, decode_responses=True)
        await r.delete(f"cache:menu:{restaurant_id}")
        
        res = await db.execute(select(Restaurant.slug).where(Restaurant.id == restaurant_id))
        slug = res.scalar_one_or_none()
        if slug:
            await r.delete(f"cache:menu:{slug}")
            
        await r.aclose()
    except Exception:
        pass # Fail open, don't crash on cache clear failure
"""

with open("app/api/menu.py", "r") as f:
    lines = f.readlines()

out = []
i = 0
while i < len(lines):
    line = lines[i]
    out.append(line)
    
    if line.startswith("# --- Helper ---"):
        out.append(helper_code)
        
    elif "return new_cat" in line:
        out.insert(-1, "        await invalidate_menu_cache(target_res_id, db)\n")
    elif 'return {"status": "deleted"}' in line and "delete_category" in "".join(lines[i-15:i]):
        out.insert(-1, "        await invalidate_menu_cache(cat.restaurant_id, db)\n")
    elif "return new_item" in line:
        out.insert(-1, "        await invalidate_menu_cache(cat.restaurant_id, db)\n")
    elif 'return {"status": "deleted"}' in line and "delete_item" in "".join(lines[i-15:i]):
        out.insert(-1, "        await invalidate_menu_cache(item.category.restaurant_id, db)\n")
    elif "return new_group" in line:
        out.insert(-1, "        res_id = parent.category.restaurant_id if group.menu_item_id else parent.restaurant_id\n        await invalidate_menu_cache(res_id, db)\n")
    elif "return new_opt" in line:
        out.insert(-1, "        await invalidate_menu_cache(res_id, db)\n")
    elif 'return {"status": "deleted"}' in line and "delete_modifier_group" in "".join(lines[i-15:i]):
        out.insert(-1, "        await invalidate_menu_cache(res_id, db)\n")
    elif 'return {"status": "deleted"}' in line and "delete_modifier_option" in "".join(lines[i-15:i]):
        out.insert(-1, "        await invalidate_menu_cache(res_id, db)\n")
    elif "return cat" in line and "cat_id: int" in "".join(lines[i-15:i]):
        out.insert(-1, "        await invalidate_menu_cache(cat.restaurant_id, db)\n")
    elif "return item" in line and "item_id: int" in "".join(lines[i-15:i]):
        out.insert(-1, "        await invalidate_menu_cache(item.category.restaurant_id, db)\n")
    elif "return group" in line and "group_id: int" in "".join(lines[i-15:i]):
        out.insert(-1, "        await invalidate_menu_cache(res_id, db)\n")
    elif "return opt" in line and "opt_id: int" in "".join(lines[i-15:i]):
        out.insert(-1, "        await invalidate_menu_cache(res_id, db)\n")
    elif 'return {"status": "success"' in line and "copy_modifiers" in "".join(lines[i-60:i]):
        out.insert(-1, "        await invalidate_menu_cache(target_item.category.restaurant_id, db)\n")
        
    i += 1

with open("app/api/menu.py", "w") as f:
    f.writelines(out)
    
print("Updated menu.py")
