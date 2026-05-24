# signal5.py
# Whale Wallet Tracking — ETH + BASE + BTC + SOL
# Scans every 5 minutes — $1M+ transactions only

import requests
import time
from datetime import datetime, timezone

BOT_TOKEN      = "8979159570:AAEQmcziFssisIuOmvggMZ17QTtBPC4HEqg"
CHAT_ID        = "8118939134"
ETHERSCAN_KEY  = "PPXB2R4P91AFAKGZJM9E4W63W71J9ECT6K"
BASESCAN_KEY   = "PPXB2R4P91AFAKGZJM9E4W63W71J9ECT6K"
MIN_USD_VALUE  = 1_000_000
SCAN_INTERVAL  = 5 * 60
COOLDOWN_SEC   = 3600

already_alerted = set()

# ── KNOWN WHALE WALLETS ───────────────────────────────────────────────────────
WHALE_WALLETS = {
    # ── Market Makers ─────────────────────────────────────────────────────────
    "0x756d64dc5edb56740fc617628dc832ddbcfd373c": "Wintermute",
    "0x0000006daea1723962647b7e189d311d757fb793": "Wintermute",
    "0x4f3a120e72c76c22ae802d129f599bfdbc31cb81": "Jump Trading",
    "0xf584f8728b874a6a5c7a8d4d387c9aae9172d621": "Jump Trading",
    "0x53d284357ec70ce289d6d64134dfac8e511c8a3d": "Jump Trading",
    "0x0548f59fee79f8832c299e01dca5c76f034f558e": "Cumberland",
    "0x3cd751e6b0078be393132286c442345e5dc49699": "Cumberland",
    "0xf6874c88757721a02f9f5f22144b09d0af520e75": "Cumberland",
    "0xdc76cd25977e0a5ae17155770273ad58648900d3": "GSR Markets",
    "0x1522900b6dafac587d499a862861c0869be6428d": "GSR Markets",
    "0x9c67ee39e3c4954396b9142010653f17257b39cc": "Amber Group",
    "0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be": "Binance",
    "0xd551234ae421e3bcba99a0da6d736074f22192ff": "Binance",
    "0x564286362092d8e7936f0549571a803b203aaced": "Binance",
    "0x0681d8db095565fe8a346fa0277bffde9c0edbbf": "Binance",
    "0xfe9e8709d3215310075d67e3ed32a380ccf451c8": "Binance",
    "0x4e9ce36e442e55ecd9025b9a6e0d88485d628a67": "Binance",
    "0xbe0eb53f46cd790cd13851d5eff43d12404d33e8": "Binance Cold",
    "0xf977814e90da44bfa03b6295a0616a897441acec": "Binance Cold",
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance Cold",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "Binance Cold",
    # ── Coinbase ──────────────────────────────────────────────────────────────
    "0x71660c4005ba85c37ccec55d0c4493e66fe775d3": "Coinbase",
    "0x503828976d22510aad0201ac7ec88293211d23da": "Coinbase",
    "0xddfabcdc4d8ffc6d5beaf154f18b778f892a0740": "Coinbase",
    "0xa090e606e30bd747d4e6245a1517ebe430f0057e": "Coinbase",
    "0xb5d85cbf7cb3ee0d56b3bb207d5fc4b82f43f511": "Coinbase Cold",
    "0xbfff1650e0751e6f5ddb26e8c23dd4579629a0c3": "Coinbase Cold",
    # ── Kraken ────────────────────────────────────────────────────────────────
    "0x2910543af39aba0cd09dbb2d50200b3e800a63d2": "Kraken",
    "0xae2d4617c862309a3d75a0ffb358c7a5009c673f": "Kraken",
    "0x43984d578803891dfa9706bdeee6078d80cfc79e": "Kraken",
    "0xab5c66752a9e8167967685f1450532fb96d5d24f": "Kraken",
    "0xe853c56864a2ebe4576a807d26fdc4a0ada51919": "Kraken",
    # ── OKX ───────────────────────────────────────────────────────────────────
    "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b": "OKX",
    "0x236f9f97e0e62388479bf9e5ba4889e46b0273c3": "OKX",
    "0x98ec059dc3adfbdd63429454aeb0c990fba4a128": "OKX",
    # ── VC Funds ──────────────────────────────────────────────────────────────
    "0x05e793ce0c6027323ac150f6d45c2344d28b6019": "a16z",
    "0x66b870ddf78c975af5cd8edc6de25eca81791de1": "a16z",
    "0x4f8c4c7e6079390f23e8ee7c0cc43c1e1587e3da": "Paradigm",
    "0xa3a7b6f88361f48403514059f1f16c8e78d60eec": "Paradigm",
    "0x7f268357a8c2552623316e2562d90e642bb538e5": "Multicoin Capital",
    "0x3ba21b6477f48273f41d241aa3722ffb9e07e247": "Pantera Capital",
    # ── Known Whales / Rich List ──────────────────────────────────────────────
    "0x47ac0fb4f2d84898e4d9e7b4dab3c24507a6d503": "Binance Whale",
    "0x8894e0a0c962cb723c1976a4421c95949be2d4e3": "Binance Whale 2",
    "0xab7c674d6f96ab14b8f93aaaae2e57b51e6e6688": "Top ETH Holder",
    "0x1b3cb81e51011b549d78bf720b0d924ac763a7c2": "Top ETH Holder 2",
    "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae": "Ethereum Foundation",
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH Contract",
    "0x8484ef722627bf18ca5ae6bcf031c23e6e922b30": "Top Trader",
    "0xa646e29877d52b9e2de457eca09c724ff16d0a2b": "Top Trader 2",
    # ── Alameda Remnants ──────────────────────────────────────────────────────
    "0x477573f212a7bdd5f7c12889bd1ad0aa44fb82aa": "Alameda Research",
    "0xfbf0b38e30b06d3f31e51e5e2e3f350726e1ddec": "Alameda Research",
    "0x267be1c1d684f78cb4f6a176c4911b741e4ffdc0": "Alameda Remnant",
}

EXCHANGE_WALLETS = {k: v for k, v in WHALE_WALLETS.items() if v in [
    "Binance", "Binance Cold", "Coinbase", "Coinbase Cold",
    "Kraken", "OKX"
]}


def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")


def get_price(coin_id):
    try:
        r    = requests.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": coin_id, "vs_currencies": "usd"}, timeout=10)
        data = r.json()
        return float(data[coin_id]["usd"])
    except Exception:
        defaults = {"ethereum": 3000.0, "solana": 150.0, "bitcoin": 90000.0}
        return defaults.get(coin_id, 1.0)


# ── ETH WHALE SCAN ────────────────────────────────────────────────────────────
def scan_eth_whales(eth_price):
    large_txs = []
    try:
        r    = requests.get("https://api.etherscan.io/api", params={"module": "proxy", "action": "eth_blockNumber", "apikey": ETHERSCAN_KEY}, timeout=10)
        data = r.json()
        latest_block = int(data["result"], 16)
        from_block   = latest_block - 25

        scanned = 0
        for address, entity_name in list(WHALE_WALLETS.items()):
            if scanned >= 10:  # limit to 10 wallets per scan to avoid rate limit
                break
            try:
                r = requests.get("https://api.etherscan.io/api", params={
                    "module":     "account",
                    "action":     "txlist",
                    "address":    address,
                    "startblock": from_block,
                    "endblock":   latest_block,
                    "sort":       "desc",
                    "apikey":     ETHERSCAN_KEY
                }, timeout=10)

                data = r.json()
                if data.get("status") != "1" or not data.get("result"):
                    time.sleep(0.3)
                    scanned += 1
                    continue

                for tx in data["result"][:5]:  # check last 5 txs per wallet
                    try:
                        tx_hash   = tx["hash"]
                        value_eth = int(tx["value"]) / 1e18
                        value_usd = value_eth * eth_price

                        if value_usd < MIN_USD_VALUE:
                            continue
                        if tx_hash in already_alerted:
                            continue

                        from_addr     = tx["from"].lower()
                        to_addr       = tx["to"].lower() if tx["to"] else "contract"
                        from_entity   = WHALE_WALLETS.get(from_addr, None)
                        to_entity     = WHALE_WALLETS.get(to_addr, None)
                        from_exchange = from_entity in list(EXCHANGE_WALLETS.values())
                        to_exchange   = to_entity in list(EXCHANGE_WALLETS.values())

                        if to_exchange:
                            emoji  = "🔴"
                            action = f"Sent TO {to_entity} = possible SELL"
                        elif from_exchange:
                            emoji  = "🟢"
                            action = f"Received FROM {from_entity} = possible BUY"
                        else:
                            emoji  = "🐋"
                            action = "Large transfer between wallets"

                        sender_name   = from_entity or f"{from_addr[:6]}...{from_addr[-4:]}"
                        receiver_name = to_entity or f"{to_addr[:6]}...{to_addr[-4:]}"

                        large_txs.append({
                            "hash":        tx_hash,
                            "from":        sender_name,
                            "to":          receiver_name,
                            "value_eth":   value_eth,
                            "value_usd":   value_usd,
                            "action":      action,
                            "emoji":       emoji,
                            "chain":       "ETH",
                            "entity":      entity_name,
                        })

                    except Exception:
                        continue

                time.sleep(0.25)
                scanned += 1

            except Exception as e:
                print(f"[Signal5] ETH wallet error: {e}")
                scanned += 1
                continue

    except Exception as e:
        print(f"[Signal5] ETH scan error: {e}")

    return large_txs


# ── BASE CHAIN WHALE SCAN ─────────────────────────────────────────────────────
def scan_base_whales(eth_price):
    large_txs = []
    try:
        r    = requests.get("https://api.basescan.org/api", params={"module": "proxy", "action": "eth_blockNumber", "apikey": BASESCAN_KEY}, timeout=10)
        data = r.json()
        latest_block = int(data["result"], 16)
        from_block   = latest_block - 25

        scanned = 0
        for address, entity_name in list(WHALE_WALLETS.items()):
            if scanned >= 5:
                break
            try:
                r = requests.get("https://api.basescan.org/api", params={
                    "module":     "account",
                    "action":     "txlist",
                    "address":    address,
                    "startblock": from_block,
                    "endblock":   latest_block,
                    "sort":       "desc",
                    "apikey":     BASESCAN_KEY
                }, timeout=10)

                data = r.json()
                if data.get("status") != "1" or not data.get("result"):
                    time.sleep(0.3)
                    scanned += 1
                    continue

                for tx in data["result"][:5]:
                    try:
                        tx_hash   = tx["hash"]
                        value_eth = int(tx["value"]) / 1e18
                        value_usd = value_eth * eth_price

                        if value_usd < MIN_USD_VALUE:
                            continue
                        if tx_hash in already_alerted:
                            continue

                        from_addr   = tx["from"].lower()
                        to_addr     = tx["to"].lower() if tx["to"] else "contract"
                        from_entity = WHALE_WALLETS.get(from_addr, None)
                        to_entity   = WHALE_WALLETS.get(to_addr, None)
                        to_exchange = to_entity in list(EXCHANGE_WALLETS.values())
                        from_exchange = from_entity in list(EXCHANGE_WALLETS.values())

                        if to_exchange:
                            emoji  = "🔴"
                            action = f"Sent TO {to_entity} = possible SELL"
                        elif from_exchange:
                            emoji  = "🟢"
                            action = f"Received FROM {from_entity} = possible BUY"
                        else:
                            emoji  = "🐋"
                            action = "Large BASE transfer"

                        sender_name   = from_entity or f"{from_addr[:6]}...{from_addr[-4:]}"
                        receiver_name = to_entity or f"{to_addr[:6]}...{to_addr[-4:]}"

                        large_txs.append({
                            "hash":      tx_hash,
                            "from":      sender_name,
                            "to":        receiver_name,
                            "value_eth": value_eth,
                            "value_usd": value_usd,
                            "action":    action,
                            "emoji":     emoji,
                            "chain":     "BASE",
                            "entity":    entity_name,
                        })

                    except Exception:
                        continue

                time.sleep(0.25)
                scanned += 1

            except Exception as e:
                print(f"[Signal5] BASE wallet error: {e}")
                scanned += 1
                continue

    except Exception as e:
        print(f"[Signal5] BASE scan error: {e}")

    return large_txs


# ── BTC WHALE SCAN ────────────────────────────────────────────────────────────
def scan_btc_whales(btc_price):
    large_txs = []
    try:
        r    = requests.get("https://blockchain.info/unconfirmed-transactions?format=json&limit=30", timeout=15)
        data = r.json()
        txs  = data.get("txs", [])

        for tx in txs:
            try:
                tx_hash   = tx.get("hash")
                if not tx_hash or tx_hash in already_alerted:
                    continue

                total_out = sum(o.get("value", 0) for o in tx.get("out", [])) / 1e8
                value_usd = total_out * btc_price

                if value_usd < MIN_USD_VALUE:
                    continue

                inputs    = tx.get("inputs", [])
                from_addr = inputs[0]["prev_out"].get("addr", "unknown") if inputs and "prev_out" in inputs[0] else "unknown"

                large_txs.append({
                    "hash":      tx_hash,
                    "from":      f"{from_addr[:8]}...{from_addr[-6:]}",
                    "to":        "multiple outputs",
                    "value_btc": total_out,
                    "value_usd": value_usd,
                    "action":    "Large BTC transfer detected",
                    "emoji":     "🐋",
                    "chain":     "BTC",
                    "entity":    "Unknown BTC Whale",
                })

            except Exception:
                continue

    except Exception as e:
        print(f"[Signal5] BTC scan error: {e}")

    return large_txs


# ── SOL WHALE SCAN ────────────────────────────────────────────────────────────
def scan_sol_whales(sol_price):
    large_txs = []
    try:
        r = requests.get(
            "https://public-api.solscan.io/transaction/last",
            params={"limit": 20},
            headers={"accept": "application/json"},
            timeout=10
        )
        if r.status_code != 200:
            return []

        data = r.json()
        for tx in data:
            try:
                tx_hash    = tx.get("txHash") or tx.get("signature")
                if not tx_hash or tx_hash in already_alerted:
                    continue

                lamports   = tx.get("lamport", 0)
                sol_amount = lamports / 1e9
                value_usd  = sol_amount * sol_price

                if value_usd < MIN_USD_VALUE:
                    continue

                signer = tx.get("signer", ["unknown"])
                from_addr = signer[0] if signer else "unknown"

                large_txs.append({
                    "hash":      tx_hash,
                    "from":      f"{from_addr[:6]}...{from_addr[-4:]}",
                    "to":        "unknown",
                    "value_sol": sol_amount,
                    "value_usd": value_usd,
                    "action":    "Large SOL transfer detected",
                    "emoji":     "🌊",
                    "chain":     "SOL",
                    "entity":    "SOL Whale",
                })

            except Exception:
                continue

    except Exception as e:
        print(f"[Signal5] SOL scan error: {e}")

    return large_txs


# ── FORMAT AND SEND ALERT ─────────────────────────────────────────────────────
def send_whale_alert(tx):
    try:
        if tx["chain"] == "ETH":
            amount_text = f"{tx['value_eth']:,.2f} ETH (${tx['value_usd']/1e6:.2f}M)"
        elif tx["chain"] == "BASE":
            amount_text = f"{tx['value_eth']:,.2f} ETH on BASE (${tx['value_usd']/1e6:.2f}M)"
        elif tx["chain"] == "BTC":
            amount_text = f"{tx['value_btc']:,.4f} BTC (${tx['value_usd']/1e6:.2f}M)"
        elif tx["chain"] == "SOL":
            amount_text = f"{tx['value_sol']:,.2f} SOL (${tx['value_usd']/1e6:.2f}M)"
        else:
            amount_text = f"${tx['value_usd']/1e6:.2f}M"

        hash_short = tx["hash"][:10] + "..." + tx["hash"][-8:]

        msg = (
            f"{tx['emoji']} *WHALE ALERT — {tx['chain']}*\n"
            f"────────────────────\n"
            f"🏢 Entity  : `{tx['entity']}`\n"
            f"💰 Amount  : `{amount_text}`\n"
            f"📤 From    : `{tx['from']}`\n"
            f"📥 To      : `{tx['to']}`\n"
            f"⚡ Action  : {tx['action']}\n"
            f"🔗 Hash    : `{hash_short}`\n"
            f"⏰ Time    : `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}`"
        )

        send_telegram(msg)
        already_alerted.add(tx["hash"])
        time.sleep(0.5)

    except Exception as e:
        print(f"[Signal5] Alert error: {e}")


# ── MAIN RUN LOOP ─────────────────────────────────────────────────────────────
def run():
    send_telegram(
        "5️⃣ *Signal 5 Started*\n"
        "────────────────────\n"
        "🐋 Whale Tracking | ETH + BASE + BTC + SOL\n"
        "💰 Min size: $1M+\n"
        "👥 Tracking: Market makers, Exchanges, VCs, Top holders\n"
        "⏱ Scans every 5 minutes"
    )

    while True:
        try:
            print(f"\n[Signal5] Scanning whales...")

            eth_price = get_price("ethereum")
            sol_price = get_price("solana")
            btc_price = get_price("bitcoin")

            all_txs = []
            all_txs += scan_eth_whales(eth_price)
            all_txs += scan_base_whales(eth_price)
            all_txs += scan_btc_whales(btc_price)
            all_txs += scan_sol_whales(sol_price)

            print(f"[Signal5] Found {len(all_txs)} whale transactions")

            for tx in all_txs:
                send_whale_alert(tx)

            if not all_txs:
                print("[Signal5] No whale transactions above $1M this scan")

        except Exception as e:
            print(f"[Signal5] Scan error: {e}")
            send_telegram(f"⚠️ Signal 5 error: `{e}`")

        time.sleep(SCAN_INTERVAL)