"""
Redmi Tracker CLI.
"""
import os
import csv
import sys
from datetime import datetime
from typing import Optional
import httpx
import typer
from rich.console import Console
from rich.table import Table
from dotenv import load_dotenv

load_dotenv()
app = typer.Typer(help="Redmi Tracker CLI - Manage device tracking and geofences")
console = Console()

API_BASE = os.getenv("API_BASE", "http://localhost:8000")

def get_headers() -> dict:
    api_key = os.getenv("API_KEY", "")
    if not api_key:
        console.print("[red]Error: API_KEY environment variable not set[/red]")
        sys.exit(1)
    return {"X-API-Key": api_key, "Content-Type": "application/json"}

@app.command("ping")
def show_latest_ping() -> None:
    try:
        response = httpx.get(f"{API_BASE}/location/latest", headers=get_headers())
        response.raise_for_status()
        data = response.json()
        console.print("
[bold blue]Latest Ping[/bold blue]")
        console.print(f"  ID: {data['id']}")
        console.print(f"  Latitude: {data['latitude']:.6f}")
        console.print(f"  Longitude: {data['longitude']:.6f}")
        console.print(f"  Battery: {data['battery']}%" if data['battery'] else "  Battery: N/A")
        console.print(f"  Recorded: {data['recorded_at']}")
    except httpx.HTTPError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

@app.command("history")
def show_history(n: int = typer.Option(20, "--n", help="Number of records to show")) -> None:
    try:
        response = httpx.get(f"{API_BASE}/location/history?limit={n}", headers=get_headers())
        response.raise_for_status()
        data = response.json()
        table = Table(title=f"Location History (Last {data['total']} pings)")
        table.add_column("ID", style="cyan")
        table.add_column("Latitude", style="green")
        table.add_column("Longitude", style="green")
        table.add_column("Battery", style="yellow")
        table.add_column("Recorded At", style="magenta")

        for loc in data["data"]:
            battery = f"{loc['battery']}%" if loc['battery'] else "N/A"
            table.add_row(str(loc["id"]), f"{loc['latitude']:.6f}", f"{loc['longitude']:.6f}", battery, loc["recorded_at"])
        console.print(table)
    except httpx.HTTPError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

@app.command("stats")
def show_stats() -> None:
    try:
        response = httpx.get(f"{API_BASE}/stats", headers=get_headers())
        response.raise_for_status()
        data = response.json()
        console.print("
[bold blue]System Statistics[/bold blue]")
        console.print(f"  Total Pings: {data['total_pings']}")
        console.print(f"  Pings Last Hour: {data['pings_last_hour']}")
        console.print(f"  Last Seen: {data['last_seen'] or 'Never'}")
        if data['last_known_position']:
            console.print(f"  Last Position: {data['last_known_position']['latitude']}, {data['last_known_position']['longitude']}")
        console.print(f"  Last Battery: {data['last_battery']}%" if data['last_battery'] else "  Last Battery: N/A")
        console.print(f"  Avg Battery (24h): {data['avg_battery_24h']:.1f}%" if data['avg_battery_24h'] else "  Avg Battery (24h): N/A")
        console.print(f"  Uptime Score (24h): {data['uptime_score_24h']:.1f}%")
        console.print(f"  Active Geofences: {data['geofences_active']}")
        console.print(f"  Alerts (24h): {data['alerts_sent_24h']}")
    except httpx.HTTPError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

@app.command("fence")
def manage_geofences(
    action: str = typer.Argument(..., help="Action: list, add, or delete"),
    fence_id: Optional[int] = typer.Argument(None, help="Geofence ID for delete")
) -> None:
    if action == "list":
        try:
            response = httpx.get(f"{API_BASE}/geofence", headers=get_headers())
            response.raise_for_status()
            fences = response.json()
            if not fences:
                console.print("[yellow]No active geofences[/yellow]")
                return
            table = Table(title="Active Geofences")
            table.add_column("ID", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Latitude", style="yellow")
            table.add_column("Longitude", style="yellow")
            table.add_column("Radius (m)", style="magenta")
            for fence in fences:
                table.add_row(str(fence["id"]), fence["name"], f"{fence['latitude']:.6f}", f"{fence['longitude']:.6f}", str(fence["radius_meters"]))
            console.print(table)
        except httpx.HTTPError as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)
    elif action == "add":
        name = typer.prompt("Geofence Name")
        lat = typer.prompt("Latitude", type=float)
        lon = typer.prompt("Longitude", type=float)
        radius = typer.prompt("Radius (meters)", type=float)
        payload = {"name": name, "latitude": lat, "longitude": lon, "radius_meters": radius}
        try:
            response = httpx.post(f"{API_BASE}/geofence", json=payload, headers=get_headers())
            response.raise_for_status()
            fence = response.json()
            console.print(f"[green]Geofence created: {fence['name']} (ID: {fence['id']})[/green]")
        except httpx.HTTPError as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)
    elif action == "delete":
        if fence_id is None:
            console.print("[red]Error: fence_id required for delete[/red]")
            sys.exit(1)
        try:
            response = httpx.delete(f"{API_BASE}/geofence/{fence_id}", headers=get_headers())
            response.raise_for_status()
            console.print("[green]Geofence deactivated[/green]")
        except httpx.HTTPError as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)
    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        sys.exit(1)

@app.command("export")
def export_history(n: int = typer.Option(100, "--n", help="Max records to export")) -> None:
    output = f"locations_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    try:
        response = httpx.get(f"{API_BASE}/location/history?limit={n}", headers=get_headers())
        response.raise_for_status()
        data = response.json()
        with open(output, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "latitude", "longitude", "battery", "recorded_at", "created_at"])
            for loc in data["data"]:
                writer.writerow([loc["id"], loc["latitude"], loc["longitude"], loc["battery"] or "", loc["recorded_at"], loc["created_at"]])
        console.print(f"[green]Exported {len(data['data'])} records to {output}[/green]")
    except httpx.HTTPError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

if __name__ == "__main__":
    app()
