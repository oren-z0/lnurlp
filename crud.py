from typing import List, Optional, Union
import os

from lnbits.helpers import urlsafe_short_hash, insert_query, update_query
from lnbits.settings import settings as lnbits_settings

from . import db
from .models import CreatePayLinkData, LnurlpSettings, ExtendedLnurlpSettings, PayLink
from .nostr.key import PrivateKey
from .services import check_lnaddress_format


async def get_or_create_lnurlp_settings() -> ExtendedLnurlpSettings:
    row = await db.fetchone("SELECT * FROM lnurlp.settings LIMIT 1")
    lnbits_nostr2http_relays = []
    if lnbits_settings.lnbits_nostr2http_relays_filepath and os.path.exists(lnbits_settings.lnbits_nostr2http_relays_filepath):
        with open(lnbits_settings.lnbits_nostr2http_relays_filepath, "r") as lnbits_nostr2http_relays_file:
            lines = [line.strip() for line in lnbits_nostr2http_relays_file.read().split("\n")]    
    if row:
        return ExtendedLnurlpSettings(lnbits_nostr2http_relays=lnbits_nostr2http_relays, **row)
    else:
        nostr_private_key = PrivateKey().hex()
        settings = LnurlpSettings(nostr_private_key=nostr_private_key)
        await db.execute(
            insert_query("lnurlp.settings", settings),
            (*settings.dict().values(),)
        )
        return ExtendedLnurlpSettings(
            lnbits_nostr2http_relays=lnbits_nostr2http_relays,
            nostr_private_key=nostr_private_key,
        )


async def update_lnurlp_settings(settings: ExtendedLnurlpSettings) -> ExtendedLnurlpSettings:
    db_settings = LnurlpSettings(nostr_private_key=settings.nostr_private_key)
    await db.execute(
        update_query("lnurlp.settings", db_settings, where=""),
        (*db_settings.dict().values(),)
    )
    if lnbits_settings.lnbits_nostr2http_relays_filepath:
        os.makedirs(os.path.dirname(lnbits_settings.lnbits_nostr2http_relays_filepath), exist_ok=True)
        with open(lnbits_settings.lnbits_nostr2http_relays_filepath, "w") as lnbits_nostr2http_relays_file:
            lnbits_nostr2http_relays_file.write(settings.lnbits_nostr2http_relays.join("\n"))
    return settings


async def delete_lnurlp_settings() -> None:
    await db.execute("DELETE FROM lnurlp.settings")
    if lnbits_settings.lnbits_nostr2http_relays_filepath and os.path.exists(lnbits_settings.lnbits_nostr2http_relays_filepath):
        os.remove(lnbits_settings.lnbits_nostr2http_relays_filepath)


async def check_lnaddress_not_exists(username: str) -> bool:
    # check if lnaddress username exists in the database when creating a new entry
    row = await db.fetchall(
        "SELECT username FROM lnurlp.pay_links WHERE username = ?", (username,)
    )
    if row:
        raise Exception("Username already exists. Try a different one.")
    else:
        return True


async def create_pay_link(data: CreatePayLinkData, wallet_id: str) -> PayLink:
    if data.username:
        await check_lnaddress_format(data.username)
        await check_lnaddress_not_exists(data.username)

    link_id = urlsafe_short_hash()[:6]

    result = await db.execute(
        """
        INSERT INTO lnurlp.pay_links (
            id,
            wallet,
            description,
            min,
            max,
            served_meta,
            served_pr,
            webhook_url,
            webhook_headers,
            webhook_body,
            success_text,
            success_url,
            comment_chars,
            currency,
            fiat_base_multiplier,
            username,
            zaps

        )
        VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            link_id,
            wallet_id,
            data.description,
            data.min,
            data.max,
            data.webhook_url,
            data.webhook_headers,
            data.webhook_body,
            data.success_text,
            data.success_url,
            data.comment_chars,
            data.currency,
            data.fiat_base_multiplier,
            data.username,
            data.zaps,
        ),
    )
    assert result

    link = await get_pay_link(link_id)
    assert link, "Newly created link couldn't be retrieved"
    return link


async def get_address_data(username: str) -> Optional[PayLink]:
    row = await db.fetchone(
        "SELECT * FROM lnurlp.pay_links WHERE username = ?", (username,)
    )
    return PayLink.from_row(row) if row else None


async def get_pay_link(link_id: str) -> Optional[PayLink]:
    row = await db.fetchone("SELECT * FROM lnurlp.pay_links WHERE id = ?", (link_id,))
    return PayLink.from_row(row) if row else None


async def get_pay_links(wallet_ids: Union[str, List[str]]) -> List[PayLink]:
    if isinstance(wallet_ids, str):
        wallet_ids = [wallet_ids]

    q = ",".join(["?"] * len(wallet_ids))
    rows = await db.fetchall(
        f"""
        SELECT * FROM lnurlp.pay_links WHERE wallet IN ({q})
        ORDER BY Id
        """,
        (*wallet_ids,),
    )
    return [PayLink.from_row(row) for row in rows]


async def update_pay_link(link_id: str, **kwargs) -> Optional[PayLink]:
    if "username" in kwargs and len(kwargs["username"] or "") > 0:
        await check_lnaddress_format(kwargs["username"])
        await check_lnaddress_not_exists(kwargs["username"])

    q = ", ".join([f"{field[0]} = ?" for field in kwargs.items()])
    await db.execute(
        f"UPDATE lnurlp.pay_links SET {q} WHERE id = ?", (*kwargs.values(), link_id)
    )
    row = await db.fetchone("SELECT * FROM lnurlp.pay_links WHERE id = ?", (link_id,))
    return PayLink.from_row(row) if row else None


async def increment_pay_link(link_id: str, **kwargs) -> Optional[PayLink]:
    q = ", ".join([f"{field[0]} = {field[0]} + ?" for field in kwargs.items()])
    await db.execute(
        f"UPDATE lnurlp.pay_links SET {q} WHERE id = ?", (*kwargs.values(), link_id)
    )
    row = await db.fetchone("SELECT * FROM lnurlp.pay_links WHERE id = ?", (link_id,))
    return PayLink.from_row(row) if row else None


async def delete_pay_link(link_id: str) -> None:
    await db.execute("DELETE FROM lnurlp.pay_links WHERE id = ?", (link_id,))
