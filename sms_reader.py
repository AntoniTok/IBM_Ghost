#!/usr/bin/env python3
"""
Bluetooth MAP SMS Reader for Granite Ghost - Elderly Companion Device
Reads unread SMS messages from a paired phone via Bluetooth MAP profile.
"""
import dbus
import dbus.service
import dbus.mainloop.glib
import json
import time
import logging
import os
from datetime import datetime, timezone

from config import BT_DEVICE_ADDRESS, SMS_OUTPUT, SMS_MARK_READ

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BUS_NAME      = "org.bluez"
MAP_IFACE     = "org.bluez.obex.MessageAccess1"
MSG_IFACE     = "org.bluez.obex.Message1"
CLIENT_IFACE  = "org.bluez.obex.Client1"
OBEX_BUS      = "org.bluez.obex"
OBEX_PATH     = "/org/bluez/obex"
PROPS_IFACE   = "org.freedesktop.DBus.Properties"


def get_obex_client(bus):
    obj = bus.get_object(OBEX_BUS, OBEX_PATH)
    return dbus.Interface(obj, CLIENT_IFACE)


def create_map_session(client, device_address):
    log.info(f"Creating MAP session with {device_address} ...")
    session_path = client.CreateSession(
        device_address,
        {"Target": dbus.String("map", variant_level=1)},
    )
    log.info(f"Session created: {session_path}")
    return str(session_path)


def get_map_interface(bus, session_path):
    obj = bus.get_object(OBEX_BUS, session_path)
    return dbus.Interface(obj, MAP_IFACE)


def set_folder(map_iface, folder="telecom/msg/inbox"):
    for part in folder.split("/"):
        map_iface.SetFolder(part)


def list_messages(map_iface, unread_only=True):
    filters = {}
    if unread_only:
        filters["ReadStatus"] = dbus.String("unread", variant_level=1)

    raw = map_iface.ListMessages("", filters)
    messages = []
    try:
        items = raw.items()
    except AttributeError:
        items = ((item[0], item[1]) for item in raw)

    for obj_path, props in items:
        try:
            messages.append((str(obj_path), {str(k): v for k, v in props.items()}))
        except Exception as e:
            log.warning(f"Could not parse message entry: {e}")
    return messages


def get_message_body(bus, obj_path, tmp_dir="/tmp"):
    msg_obj   = bus.get_object(OBEX_BUS, obj_path)
    msg_iface = dbus.Interface(msg_obj, MSG_IFACE)
    dest_path = os.path.join(tmp_dir, f"sms_{os.path.basename(obj_path)}.bmsg")
    transfer_path, _ = msg_iface.Get(dest_path, dbus.Boolean(True))
    _wait_for_transfer(bus, str(transfer_path))
    body = _parse_bmessage(dest_path)
    try:
        os.remove(dest_path)
    except OSError:
        pass
    return body


def _wait_for_transfer(bus, transfer_path, timeout=15):
    transfer_obj = bus.get_object(OBEX_BUS, transfer_path)
    try:
        props_iface = dbus.Interface(transfer_obj, PROPS_IFACE)
        filename = str(props_iface.Get("org.bluez.obex.Transfer1", "Filename"))
    except Exception:
        filename = None

    deadline  = time.time() + timeout
    last_size = -1
    while time.time() < deadline:
        time.sleep(0.4)
        if filename and os.path.exists(filename):
            size = os.path.getsize(filename)
            if size > 0 and size == last_size:
                return
            last_size = size
        else:
            time.sleep(2)
            return
    raise TimeoutError(f"Transfer timed out: {transfer_path}")


def _parse_bmessage(filepath):
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return ""

    in_msg     = False
    body_lines = []
    for line in lines:
        stripped = line.rstrip("\r\n")
        if stripped == "BEGIN:MSG":
            in_msg = True
            continue
        if stripped == "END:MSG":
            break
        if in_msg:
            body_lines.append(stripped)
    return "\n".join(body_lines).strip()


def mark_as_read(bus, obj_path):
    msg_obj   = bus.get_object(OBEX_BUS, obj_path)
    msg_iface = dbus.Interface(msg_obj, MSG_IFACE)
    msg_iface.SetProperty("Read", dbus.Boolean(True))


def format_sms_summary(messages):
    if not messages:
        return "You have no unread text messages."
    count = len(messages)
    intro = f"You have {count} unread text message{'s' if count != 1 else ''}."
    descriptions = []
    for msg in messages[:3]:
        sender  = msg.get("sender") or msg.get("sender_number") or "Unknown"
        body    = msg.get("body") or msg.get("subject") or ""
        snippet = (body[:60] + "...") if len(body) > 60 else body
        line    = f"From {sender}"
        if snippet:
            line += f": {snippet}"
        descriptions.append(line)
    if count > 3:
        descriptions.append(f"and {count - 3} more")
    return intro + " " + ". ".join(descriptions) + "."


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    session_bus = dbus.SessionBus()
    client      = get_obex_client(session_bus)

    try:
        session_path = create_map_session(client, BT_DEVICE_ADDRESS)
    except dbus.exceptions.DBusException as exc:
        log.error(f"Could not create MAP session: {exc}")
        raise

    map_iface = get_map_interface(session_bus, session_path)

    try:
        set_folder(map_iface, "telecom/msg/inbox")
    except dbus.exceptions.DBusException:
        log.warning("Could not navigate to telecom/msg/inbox, trying inbox directly.")
        try:
            map_iface.SetFolder("inbox")
        except dbus.exceptions.DBusException as exc:
            log.error(f"Folder navigation failed: {exc}")
            raise

    messages = list_messages(map_iface, unread_only=True)
    log.info(f"Found {len(messages)} unread message(s).")

    # Only fetch the 5 most recent to stay within the service timeout
    MAX_FETCH = 10
    fetch_list = messages[:MAX_FETCH]
    if len(messages) > MAX_FETCH:
        log.info(f"  Limiting fetch to {MAX_FETCH} most recent (of {len(messages)})")

    results = []
    for obj_path, props in fetch_list:
        log.info(f"  Fetching: {obj_path}")
        subject = props.get("Subject", "")
        try:
            body = get_message_body(session_bus, obj_path)
        except Exception as exc:
            log.warning(f"  Could not fetch body for {obj_path}: {exc}")
            body = None

        resolved_body = body if body else subject if subject else None
        entry = {
            "handle":        props.get("Handle", ""),
            "subject":       subject,
            "sender":        props.get("SenderName", props.get("SenderAddressing", "")),
            "sender_number": props.get("SenderAddressing", ""),
            "timestamp":     props.get("Timestamp", ""),
            "read":          bool(props.get("Read", False)),
            "body":          resolved_body,
            "fetched_at":    datetime.now(timezone.utc).isoformat(),
        }
        results.append(entry)

        if SMS_MARK_READ:
            try:
                mark_as_read(session_bus, obj_path)
                entry["marked_read"] = True
            except Exception as exc:
                log.warning(f"  Could not mark as read: {exc}")

    output = {
        "service":      "sms",
        "status":       "success",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "content":  format_sms_summary(results),
            "messages": results,
        },
    }

    SMS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    SMS_OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    log.info(f"Saved {len(results)} messages → {SMS_OUTPUT}")

    try:
        client.RemoveSession(session_path)
    except Exception:
        pass


if __name__ == "__main__":
    main()
