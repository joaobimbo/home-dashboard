#!/usr/bin/env python3
"""Manual pairing helper for Daikin Madoka (BRC1H) BLE thermostats.

Linux only (relies on `bluetoothctl`). Run this by hand on the machine that
hosts the dashboard, once per Madoka unit, then re-run the dashboard.

Usage:
    python modules/daikin/pair.py
"""
import argparse
import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

INSTRUCTIONS = """
Antes de comecar:
  1. No ecra do Madoka (BRC1H), entra no menu de definicoes e ativa o modo
     de emparelhamento Bluetooth (se ja estiver emparelhado com a app
     Daikin Onecta/Madoka noutro telemovel, desliga esse emparelhamento
     primeiro - o Madoka so aceita um cliente BLE de cada vez).
  2. Confirma que o adaptador Bluetooth do Raspberry Pi esta ligado
     (`bluetoothctl show` deve mostrar "Powered: yes").

Vou abrir o `bluetoothctl` interativo. Dentro dele corre, por esta ordem:
  agent off
  agent KeyboardDisplay
  default-agent
  scan on
  (espera ate veres o MAC do Madoka na lista, normalmente "BRC1H..." ou
   fabricante Daikin)
  scan off
  pair <MAC_DO_MADOKA>
  (confirma o codigo tanto no terminal como no ecra do Madoka)
  trust <MAC_DO_MADOKA>
  exit
"""


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "daikin-device"


def load_existing(path: Path) -> List[dict]:
    if not path.exists():
        return []
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def write_config(path: Path, devices: List[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(devices, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )


def prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


async def verify_connection(address: str, adapter: str, timeout: float = 15.0) -> str:
    try:
        from pymadoka.controller import Controller
        from pymadoka.connection import discover_devices, force_device_disconnect
    except ImportError:
        return "pymadoka nao instalado - saltei a verificacao (corre `pip install pymadoka`)."

    async def attempt():
        await force_device_disconnect(address)
        await discover_devices(timeout=4, adapter=adapter)
        madoka = Controller(address, adapter=adapter)
        await madoka.start()
        try:
            info = await madoka.read_info()
            return f"Ligacao OK. Info do dispositivo: {info}"
        finally:
            await madoka.stop()

    try:
        return await asyncio.wait_for(attempt(), timeout=timeout)
    except Exception as exc:
        return f"Nao consegui confirmar a ligacao ({exc}). Podes tentar mais tarde a partir do dashboard."


def main():
    default_output = Path(__file__).resolve().parent / "devices.json"
    parser = argparse.ArgumentParser(
        description="Pair a Daikin Madoka (BRC1H) BLE thermostat and register it"
    )
    parser.add_argument(
        "--output", default=str(default_output), help="Output JSON config path"
    )
    parser.add_argument(
        "--skip-bluetoothctl",
        action="store_true",
        help="Skip launching bluetoothctl (use if already paired/trusted)",
    )
    args = parser.parse_args()

    if sys.platform != "linux":
        print(
            "Aviso: este script foi feito para correr em Linux (usa bluetoothctl). "
            "Continuar pode nao funcionar neste SO."
        )

    print(INSTRUCTIONS)

    if not args.skip_bluetoothctl:
        input("Prime Enter para abrir o bluetoothctl...")
        subprocess.run(["bluetoothctl"])

    print("\nAgora regista o dispositivo no dashboard.\n")
    address = ""
    while not MAC_RE.match(address):
        address = prompt("MAC address do Madoka (ex: AA:BB:CC:DD:EE:FF)")
        if not MAC_RE.match(address):
            print("Formato invalido, tenta outra vez.")
    address = address.upper()

    display_name = prompt("Nome a mostrar no dashboard", "Ar Condicionado")
    room = prompt("Sala", "Casa")
    adapter = prompt("Adaptador Bluetooth", "hci0")

    print("\nA verificar a ligacao (pode demorar ate 15s)...")
    result = asyncio.run(verify_connection(address, adapter))
    print(result)

    output_path = Path(args.output)
    devices = load_existing(output_path)
    device_id = slugify(f"{display_name}-{address}")

    entry = {
        "id": device_id,
        "display_name": display_name,
        "other_names": [],
        "room": room,
        "address": address,
        "adapter": adapter,
        "image": "",
    }

    devices = [d for d in devices if d.get("id") != device_id and d.get("address") != address]
    devices.append(entry)

    write_config(output_path, devices)
    print(f"\nGravado em {output_path}")
    print(f"id: {device_id}")


if __name__ == "__main__":
    main()
