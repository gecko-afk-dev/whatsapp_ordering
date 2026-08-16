import logging
import calendar
from typing import Optional
from datetime import datetime
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.models import Restaurant, Order, OrderStatus

logger = logging.getLogger(__name__)

async def generate_monthly_insights_report(
    db: AsyncSession, 
    restaurant_id: int, 
    month: Optional[int] = None, 
    year: Optional[int] = None
) -> Response:
    now = datetime.utcnow()
    month = month or now.month
    year = year or now.year

    r = await db.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    restaurant = r.scalar_one_or_none()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    _, last_day = calendar.monthrange(year, month)
    period_start = datetime(year, month, 1)
    period_end = datetime(year, month, last_day, 23, 59, 59)

    agg = await db.execute(
        select(
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_price), 0),
        ).where(
            Order.restaurant_id == restaurant.id,
            Order.status != OrderStatus.CANCELLED,
            Order.created_at >= period_start,
            Order.created_at <= period_end,
        )
    )
    total_orders, total_gmv = agg.first()
    
    # Null safe defaults
    total_orders = int(total_orders or 0)
    total_gmv = float(total_gmv or 0.0)
    prep_time = 0.0  # Placeholder for prep time as it's not currently queried directly

    month_name = calendar.month_name[month]

    html_content = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="utf-8">
        <title>GEQO Rapport Mensuel - {restaurant.name}</title>
        <style>
            body {{
                font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                background-color: #FAFAFA;
                color: #111;
                margin: 0;
                padding: 40px;
            }}
            .container {{
                max-width: 800px;
                margin: 0 auto;
                background: #FFF;
                padding: 40px;
                border-radius: 12px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.05);
            }}
            .header {{
                border-bottom: 2px solid #F59E0B;
                padding-bottom: 20px;
                margin-bottom: 30px;
            }}
            h1 {{
                color: #F59E0B;
                margin: 0 0 10px 0;
                font-size: 28px;
                text-transform: uppercase;
                letter-spacing: -0.5px;
            }}
            .subtitle {{
                color: #555;
                font-size: 14px;
                margin: 0;
            }}
            .kpi-grid {{
                display: grid;
                grid-template-columns: 1fr;
                gap: 20px;
            }}
            .kpi-card {{
                background: #F9F9F9;
                border: 1px solid #EEE;
                padding: 20px;
                border-radius: 8px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            .kpi-label {{
                font-size: 12px;
                color: #666;
                text-transform: uppercase;
                letter-spacing: 0.8px;
                font-weight: bold;
            }}
            .kpi-val {{
                font-size: 20px;
                font-weight: 900;
                color: #111;
            }}
            .kpi-val.highlight {{
                color: #F59E0B;
            }}
            .footer {{
                margin-top: 40px;
                text-align: center;
                font-size: 10px;
                color: #999;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>GEQO Analytics</h1>
                <p class="subtitle"><strong>Restaurant :</strong> {restaurant.name} (ID: {restaurant.id})<br>
                <strong>Période :</strong> {month_name} {year}</p>
            </div>
            
            <div class="kpi-grid">
                <div class="kpi-card">
                    <span class="kpi-label">Total Commandes</span>
                    <span class="kpi-val">{total_orders}</span>
                </div>
                <div class="kpi-card">
                    <span class="kpi-label">Volume d'Affaires (GMV)</span>
                    <span class="kpi-val highlight">{total_gmv:.2f} MAD</span>
                </div>
                <div class="kpi-card">
                    <span class="kpi-label">Temps de Préparation (Moy)</span>
                    <span class="kpi-val">{prep_time:.1f} min</span>
                </div>
            </div>
            
            <div class="footer">
                Généré par GEQO Analytics Engine | Document Confidentiel
            </div>
        </div>
    </body>
    </html>
    """

    try:
        import weasyprint
        pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="geqo-report-{restaurant_id}-{year}-{month:02d}.pdf"'}
        )
    except Exception as e:
        logger.warning(f"PDF compilation failed, falling back to HTML: {e}")
        return Response(
            content=html_content, 
            media_type="text/html"
        )
