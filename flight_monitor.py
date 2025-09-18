# FLIGHT MONITOR SICURO per GitHub
# Versione migliorata del tuo script originale

import requests
import json
import smtplib
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from urllib.parse import urlencode
import time

# Carica variabili d'ambiente dal file .env
load_dotenv()

# ===== CONFIGURAZIONE DA VARIABILI D'AMBIENTE =====
# Queste vengono lette dal file .env (non committato su GitHub)
PARTENZA = os.getenv('PARTENZA', '2026-01-12')
RITORNO = os.getenv('RITORNO', '2026-02-08')
PREZZO_SOGLIA = int(os.getenv('PREZZO_SOGLIA', '1000'))
PREZZO_BUONO = int(os.getenv('PREZZO_BUONO', '1150'))
PREZZO_ATTUALE = int(os.getenv('PREZZO_ATTUALE', '1420'))
NUMERO_PASSEGGERI = int(os.getenv('NUMERO_PASSEGGERI', '4'))
FLESSIBILITA_GIORNI = int(os.getenv('FLESSIBILITA_GIORNI', '7'))

# Vincoli viaggio
MIN_DURATA_VIAGGIO = int(os.getenv('MIN_DURATA_VIAGGIO', '25'))
MAX_DURATA_VIAGGIO = int(os.getenv('MAX_DURATA_VIAGGIO', '35'))

# Notifiche
MIN_CALO_PER_NOTIFICA = int(os.getenv('MIN_CALO_PER_NOTIFICA', '20'))
SEMPRE_NOTIFICA_SOTTO = int(os.getenv('SEMPRE_NOTIFICA_SOTTO', '1200'))

# Credenziali (SICURE - da variabili d'ambiente)
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
USA_TELEGRAM = os.getenv('USA_TELEGRAM', 'True').lower() == 'true'

# Email (se non usi Telegram)
TUA_EMAIL = os.getenv('TUA_EMAIL')
PASSWORD_EMAIL = os.getenv('PASSWORD_EMAIL')

# Amadeus API (gratuita tier Self-Service con limiti)
AMADEUS_API_KEY = os.getenv('AMADEUS_API_KEY')
AMADEUS_API_SECRET = os.getenv('AMADEUS_API_SECRET')

# Ascolto comandi Telegram (richieste manuali) e siti selezionati
ASCOLTA_COMANDI_TELEGRAM = os.getenv('ASCOLTA_COMANDI_TELEGRAM', 'False').lower() == 'true'
SITI_SELEZIONATI = os.getenv('SITI_SELEZIONATI', 'amadeus,google,skyscanner,kayak,aeromexico')

# Cache semplice per token Amadeus
_AMADEUS_TOKEN_CACHE = {
    'token': None,
    'expiry': 0,
}

def amadeus_get_token():
    """Ottiene e cache un token OAuth2 Amadeus (client_credentials)."""
    now = time.time()
    if _AMADEUS_TOKEN_CACHE['token'] and now < _AMADEUS_TOKEN_CACHE['expiry'] - 60:
        return _AMADEUS_TOKEN_CACHE['token']
    url = 'https://test.api.amadeus.com/v1/security/oauth2/token'
    data = {
        'grant_type': 'client_credentials',
        'client_id': AMADEUS_API_KEY,
        'client_secret': AMADEUS_API_SECRET,
    }
    resp = requests.post(url, data=data, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    access_token = payload.get('access_token')
    expires_in = payload.get('expires_in', 1700)
    _AMADEUS_TOKEN_CACHE['token'] = access_token
    _AMADEUS_TOKEN_CACHE['expiry'] = now + int(expires_in)
    return access_token

def amadeus_search_flights(partenza, ritorno, passeggeri):
    """Chiama Flight Offers Search v2 su ambiente test (gratuito). Ritorna miglior prezzo e link sito."""
    token = amadeus_get_token()
    url = 'https://test.api.amadeus.com/v2/shopping/flight-offers'
    params = {
        'originLocationCode': 'FCO',
        'destinationLocationCode': 'MEX',
        'departureDate': partenza,
        'returnDate': ritorno,
        'adults': passeggeri,
        'currencyCode': 'EUR',
        'nonStop': 'true',
        'max': 20,
    }
    headers = {
        'Authorization': f'Bearer {token}',
    }
    resp = requests.get(url, params=params, headers=headers, timeout=20)
    if resp.status_code == 429:
        raise RuntimeError('Rate limit Amadeus superato (free tier). Riprova più tardi.')
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get('data', [])
    if not data:
        return None
    # Ordina per prezzo totale
    def price_of(offer):
        try:
            return float(offer['price']['grandTotal'])
        except Exception:
            return 1e9
    data.sort(key=price_of)
    offer = data[0]
    prezzo = price_of(offer)
    # Amadeus non fornisce deep-link. Generiamo un link utile (Google Flights) per stesse date.
    link = genera_link_offerta('Google Flights', partenza, ritorno, passeggeri)
    return {
        'prezzo': int(round(prezzo)),
        'sito': 'Amadeus',
        'link': link,
    }

def controlla_configurazione():
    """Controlla che tutte le configurazioni necessarie siano presenti"""
    
    config_mancanti = []
    
    if USA_TELEGRAM:
        if not TELEGRAM_BOT_TOKEN:
            config_mancanti.append('TELEGRAM_BOT_TOKEN')
        if not TELEGRAM_CHAT_ID:
            config_mancanti.append('TELEGRAM_CHAT_ID')
    else:
        if not TUA_EMAIL:
            config_mancanti.append('TUA_EMAIL')
        if not PASSWORD_EMAIL:
            config_mancanti.append('PASSWORD_EMAIL')
    
    # Amadeus (opzionale ma consigliato per dati reali)
    if not AMADEUS_API_KEY:
        config_mancanti.append('AMADEUS_API_KEY')
    if not AMADEUS_API_SECRET:
        config_mancanti.append('AMADEUS_API_SECRET')
    
    if config_mancanti:
        print("❌ ERRORE: Configurazioni mancanti nel file .env:")
        for config in config_mancanti:
            print(f"   - {config}")
        print("\n💡 Crea un file .env seguendo l'esempio in .env.example")
        return False
    
    return True

def genera_date_flessibili():
    """Genera combinazioni realistiche per voli diretti Aeromexico"""
    
    data_partenza_base = datetime.strptime(PARTENZA, "%Y-%m-%d")
    data_ritorno_base = datetime.strptime(RITORNO, "%Y-%m-%d")
    
    # Date realistiche partenze Aeromexico (circa 2-3 volte a settimana)
    giorni_voli_diretti = [-7, -4, -3, 0, 3, 4, 7]  # Pattern realistico
    
    combinazioni_date = []
    
    for giorni_partenza in giorni_voli_diretti:
        if abs(giorni_partenza) <= FLESSIBILITA_GIORNI:
            
            nuova_partenza = data_partenza_base + timedelta(days=giorni_partenza)
            
            # Per ogni partenza, controlla ritorni compatibili
            for giorni_ritorno in giorni_voli_diretti:
                if abs(giorni_ritorno) <= FLESSIBILITA_GIORNI:
                    
                    nuovo_ritorno = data_ritorno_base + timedelta(days=giorni_ritorno)
                    
                    # Calcola durata viaggio
                    durata = (nuovo_ritorno - nuova_partenza).days
                    
                    # Controlla vincoli di durata (25-35 giorni)
                    if MIN_DURATA_VIAGGIO <= durata <= MAX_DURATA_VIAGGIO:
                        combinazioni_date.append({
                            'partenza': nuova_partenza.strftime("%Y-%m-%d"),
                            'ritorno': nuovo_ritorno.strftime("%Y-%m-%d"),
                            'durata': durata,
                            'giorni_diff_partenza': giorni_partenza,
                            'giorni_diff_ritorno': giorni_ritorno
                        })
    
    # Ordina per durata ottimale (più vicina a 28 giorni)
    combinazioni_date.sort(key=lambda x: abs(x['durata'] - 28))
    
    print(f"📊 Generate {len(combinazioni_date)} combinazioni realistiche per voli diretti")
    return combinazioni_date

def controlla_prezzi():
    """Controlla prezzi su tutti i siti configurati"""
    
    print(f"🔍 Controllo prezzi alle {datetime.now().strftime('%H:%M')}...")
    
    try:
        # Controlla date ideali
        risultato_ideale = controlla_volo_specifico(PARTENZA, RITORNO, "DATE IDEALI")
        
        # Controlla date flessibili
        combinazioni = genera_date_flessibili()
        prezzi_trovati = []
        
        for i, combo in enumerate(combinazioni[:5]):  # Controlla solo le prime 5
            risultato = controlla_volo_specifico(combo['partenza'], combo['ritorno'], 
                                            f"FLESSIBILE {i+1}")
            if risultato:
                if risultato.get('prezzo') is None:
                    continue
                risultato['durata'] = combo['durata']
                prezzi_trovati.append(risultato)
        
        # Analizza i risultati
        analizza_risultati(risultato_ideale, prezzi_trovati)
        
    except Exception as e:
        print(f"❌ Errore generale: {e}")

def controlla_volo_specifico(partenza, ritorno, tipo_ricerca):
    """Controlla prezzo per una specifica combinazione di date"""
    
    # Headers per sembrare un browser normale
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        print(f"   🔍 {tipo_ricerca}: {partenza} → {ritorno}")
        
        # 1) Prova dati reali da Amadeus (free tier)
        offerta = amadeus_search_flights(partenza, ritorno, NUMERO_PASSEGGERI)
        if offerta:
            print(f"   💰 €{offerta['prezzo']} (Amadeus)")
            return {
                'prezzo': offerta['prezzo'],
                'partenza': partenza,
                'ritorno': ritorno,
                'sito': offerta['sito'],
                'link': offerta['link'],
                'tipo': 'ideale' if "IDEALI" in tipo_ricerca else 'flessibile'
            }
        
        # 2) Fallback: genera link/prenotazione utile (senza prezzo) usando Google Flights
        link = genera_link_offerta('Google Flights', partenza, ritorno, NUMERO_PASSEGGERI)
        print("   ⚠️ Nessuna offerta trovata su Amadeus")
        return {
            'prezzo': None,
            'partenza': partenza,
            'ritorno': ritorno,
            'sito': 'Google Flights',
            'link': link,
            'tipo': 'ideale' if "IDEALI" in tipo_ricerca else 'flessibile'
        }
        
    except Exception as e:
        print(f"   ❌ Errore per {tipo_ricerca}: {e}")
        return None

def analizza_risultati(risultato_ideale, prezzi_flessibili):
    """Analizza tutti i prezzi trovati e invia notifiche appropriate"""
    
    # Leggi ultimo prezzo salvato
    ultimo_prezzo_salvato = leggi_ultimo_prezzo()
    
    # Trova il prezzo migliore
    tutti_prezzi = []
    if risultato_ideale and risultato_ideale.get('prezzo') is not None:
        tutti_prezzi.append(risultato_ideale)
    
    tutti_prezzi.extend(prezzi_flessibili)
    
    if not tutti_prezzi:
        print("❌ Nessun prezzo trovato oggi")
        return
    
    # Ordina per prezzo migliore
    tutti_prezzi.sort(key=lambda x: x['prezzo'])
    prezzo_migliore = tutti_prezzi[0]
    
    print(f"\n🏆 MIGLIOR PREZZO OGGI: €{prezzo_migliore['prezzo']} ({prezzo_migliore['tipo']})")
    
    # Controlla se inviare notifiche
    controlla_e_invia_notifiche(prezzo_migliore, ultimo_prezzo_salvato)
    
    # Salva il nuovo prezzo
    salva_prezzo(prezzo_migliore['prezzo'], prezzo_migliore['tipo'])

def controlla_e_invia_notifiche(offerta, ultimo_prezzo):
    """Controlla se inviare notifiche basate sui criteri impostati"""
    
    prezzo = offerta['prezzo']
    
    # Controlli per diversi tipi di alert
    if prezzo <= PREZZO_SOGLIA:
        offerta['alert_type'] = "TARGET_OTTIMALE"
        invia_notifica_offerta(offerta)
        
    elif prezzo <= PREZZO_BUONO:
        offerta['alert_type'] = "PREZZO_BUONO" 
        invia_notifica_offerta(offerta)
        
    elif prezzo <= SEMPRE_NOTIFICA_SOTTO:
        offerta['alert_type'] = "SOTTO_SOGLIA"
        invia_notifica_offerta(offerta)
        
    elif prezzo < ultimo_prezzo - MIN_CALO_PER_NOTIFICA:
        # Calo significativo
        invia_notifica_calo(prezzo, ultimo_prezzo, "Significativo")
    
    else:
        print(f"💡 Prezzo €{prezzo} - nessuna notifica necessaria")

def invia_notifica_offerta(offerta):
    """Invia notifica per offerte importanti"""
    
    if USA_TELEGRAM:
        invia_telegram_offerta(offerta)
    else:
        invia_email_offerta(offerta)

def invia_notifica_calo(prezzo_nuovo, prezzo_vecchio, motivo, offerta=None):
    """Invia notifica per cali di prezzo"""
    
    if USA_TELEGRAM:
        invia_telegram_calo(prezzo_nuovo, prezzo_vecchio, motivo, offerta)
    else:
        invia_email_calo(prezzo_nuovo, prezzo_vecchio, motivo, offerta)

def invia_telegram_offerta(offerta):
    """Invia notifica Telegram per offerte"""
    
    prezzo_per_persona = offerta['prezzo']
    prezzo_totale = prezzo_per_persona * NUMERO_PASSEGGERI
    risparmio_per_persona = PREZZO_ATTUALE - prezzo_per_persona
    risparmio_totale = risparmio_per_persona * NUMERO_PASSEGGERI
    
    # Emoji e messaggio basato sul tipo di alert
    if offerta['alert_type'] == "TARGET_OTTIMALE":
        emoji = "🎯🔥"
        stato = f"TARGET OTTIMALE €{PREZZO_SOGLIA} RAGGIUNTO!"
        urgenza = "PRENOTA SUBITO!"
    elif offerta['alert_type'] == "PREZZO_BUONO":
        emoji = "✨💰"
        stato = f"PREZZO TOP €{PREZZO_BUONO} RAGGIUNTO!"
        urgenza = "Ottimo prezzo!"
    else:
        emoji = "📢💡"
        stato = f"Prezzo interessante sotto €{SEMPRE_NOTIFICA_SOTTO}"
        urgenza = "Da valutare!"
    
    messaggio = f"""{emoji} OFFERTA TROVATA! {emoji}

✈️ Aeromexico DIRETTO FCO→MEX
📅 {offerta['partenza']} → {offerta['ritorno']}
📊 Tipo: {offerta.get('tipo', 'N/A')}
🌐 Sito: {offerta.get('sito', 'N/A')}

💰 €{prezzo_per_persona}/persona
💰 €{prezzo_totale} TOTALE x{NUMERO_PASSEGGERI}

🎯 RISPARMIO: €{risparmio_totale} totale!
🟢 {stato}

🏃‍♂️ {urgenza}

🔗 Link: {offerta.get('link', 'N/A')}"""
    
    invia_messaggio_telegram(messaggio)

def invia_telegram_calo(prezzo_nuovo, prezzo_vecchio, motivo, offerta=None):
    """Invia notifica Telegram per cali di prezzo"""
    
    risparmio_per_persona = prezzo_vecchio - prezzo_nuovo
    risparmio_totale = risparmio_per_persona * NUMERO_PASSEGGERI
    prezzo_totale = prezzo_nuovo * NUMERO_PASSEGGERI
    
    extra = ""
    if offerta:
        extra = f"\n🌐 Sito: {offerta.get('sito')}\n🔗 Link: {offerta.get('link')}"

    messaggio = f"""📉 PREZZO SCESO! 📉

✈️ Aeromexico DIRETTO FCO→MEX
📅 {PARTENZA} → {RITORNO}

💰 Prima: €{prezzo_vecchio}/persona
💰 Ora: €{prezzo_nuovo}/persona
📉 Sceso di: €{risparmio_per_persona}

💰 TOTALE x{NUMERO_PASSEGGERI}: €{prezzo_totale}
🎯 RISPARMIO: €{risparmio_totale}

🟢 Calo {motivo}!{extra}"""
    
    invia_messaggio_telegram(messaggio)

def invia_messaggio_telegram(messaggio):
    """Funzione generica per inviare messaggi Telegram"""
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': messaggio
        }
        
        response = requests.post(url, data=data, timeout=10)
        
        if response.status_code == 200:
            print("📱 Notifica Telegram inviata!")
        else:
            print(f"❌ Errore Telegram: {response.text}")
            
    except Exception as e:
        print(f"❌ Errore invio Telegram: {e}")

def leggi_messaggi_telegram(offset=None):
    """Legge aggiornamenti Telegram (long polling semplice)"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        params = {}
        if offset is not None:
            params['offset'] = offset
        params['timeout'] = 25
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"❌ Errore getUpdates Telegram: {e}")
        return None

def gestisci_comando_telegram(testo):
    """Gestisce i comandi testuali dal bot."""
    txt = (testo or '').strip().lower()
    if txt in ('/start', 'start'):
        return ("👋 Ciao! Usa /prezzi per prezzi in tempo reale delle date attuali.\n"
                "Puoi usare anche: /prezzi FCO MEX 2026-01-12 2026-02-08 4")
    if txt.startswith('/prezzi'):
        # Parsing semplice: /prezzi [FCO] [MEX] [YYYY-MM-DD] [YYYY-MM-DD] [adults]
        parts = testo.split()
        origin = 'FCO'
        dest = 'MEX'
        partenza = PARTENZA
        ritorno = RITORNO
        adults = NUMERO_PASSEGGERI
        if len(parts) >= 6:
            origin, dest, partenza, ritorno, adults = parts[1], parts[2], parts[3], parts[4], int(parts[5])
        # Esegui ricerca multipla
        return prezzi_tempo_reale(origin, dest, partenza, ritorno, adults)
    return "Comando non riconosciuto. Usa /prezzi"

def prezzi_tempo_reale(origin, dest, partenza, ritorno, adults):
    """Raccoglie prezzi reali e link dai siti selezionati (Amadeus + deep link)."""
    selezionati = [s.strip().lower() for s in SITI_SELEZIONATI.split(',') if s.strip()]
    risultati = []
    # Amadeus fornisce prezzo
    if 'amadeus' in selezionati:
        try:
            off = amadeus_search_flights(partenza, ritorno, adults)
            if off:
                risultati.append({
                    'sito': 'Amadeus',
                    'prezzo': off['prezzo'],
                    'link': off['link'],
                })
        except Exception as e:
            risultati.append({'sito': 'Amadeus', 'errore': str(e)})
    # Deep links utili (senza prezzo diretto) per gli altri siti
    mapping = {
        'google': 'Google Flights',
        'skyscanner': 'Skyscanner',
        'kayak': 'Kayak',
        'aeromexico': 'Aeromexico',
    }
    for key, nome in mapping.items():
        if key in selezionati:
            try:
                link = genera_link_offerta(nome, partenza, ritorno, adults)
                risultati.append({'sito': nome, 'prezzo': None, 'link': link})
            except Exception as e:
                risultati.append({'sito': nome, 'errore': str(e)})
    # Compose message
    lines = [f"📊 Prezzi in tempo reale {origin}→{dest} {partenza}→{ritorno} (adulti: {adults})"]
    for r in risultati:
        if r.get('errore'):
            lines.append(f"- {r['sito']}: errore {r['errore']}")
        else:
            prezzo = f"€{r['prezzo']}" if r.get('prezzo') is not None else "—"
            lines.append(f"- {r['sito']}: {prezzo}\n  {r['link']}")
    return "\n".join(lines)

def invia_email_offerta(offerta):
    """Invia email per offerte (implementazione base)"""
    
    # Implementazione email semplificata
    oggetto = f"🔥 OFFERTA VOLO! €{offerta['prezzo']}"
    corpo = (
        f"Trovata offerta per €{offerta['prezzo']} dal {offerta['partenza']} al {offerta['ritorno']}\n"
        f"Sito: {offerta.get('sito', 'N/A')}\n"
        f"Link: {offerta.get('link', 'N/A')}\n"
    )
    
    invia_email(oggetto, corpo)

def invia_email_calo(prezzo_nuovo, prezzo_vecchio, motivo, offerta=None):
    """Invia email per cali di prezzo"""
    
    oggetto = f"📉 PREZZO SCESO! €{prezzo_nuovo}"
    if offerta:
        corpo = (
            f"Prezzo sceso da €{prezzo_vecchio} a €{prezzo_nuovo} ({motivo})\n"
            f"Sito: {offerta.get('sito')}\n"
            f"Link: {offerta.get('link')}\n"
        )
    else:
        corpo = f"Prezzo sceso da €{prezzo_vecchio} a €{prezzo_nuovo} ({motivo})"
    
    invia_email(oggetto, corpo)

def invia_email(oggetto, corpo):
    """Funzione generica per inviare email"""
    
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(TUA_EMAIL, PASSWORD_EMAIL)
        
        messaggio = f"Subject: {oggetto}\n\n{corpo}"
        server.sendmail(TUA_EMAIL, TUA_EMAIL, messaggio)
        server.quit()
        
        print("📧 Email inviata!")
        
    except Exception as e:
        print(f"❌ Errore invio email: {e}")

def leggi_ultimo_prezzo():
    """Legge l'ultimo prezzo salvato"""
    try:
        with open('ultimo_prezzo.txt', 'r') as f:
            return float(f.read().strip())
    except:
        return 999999  # Prima volta

def salva_prezzo(prezzo, tipo="unknown"):
    """Salva il prezzo attuale"""
    
    # Salva prezzo corrente
    with open('ultimo_prezzo.txt', 'w') as f:
        f.write(str(prezzo))
    
    # Salva nello storico
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open('storico_prezzi.txt', 'a') as f:
        f.write(f"{timestamp} - €{prezzo} ({tipo})\n")

def scegli_sito_offerta():
    """Seleziona un sito simulato da cui proviene l'offerta"""
    import random
    return random.choice(["Google Flights", "Skyscanner", "Kayak", "Aeromexico"])

def genera_link_offerta(sito, partenza, ritorno, num_passeggeri):
    """Genera un link diretto (simulato ma utile) alla ricerca per le date date"""
    origin = "FCO"
    destination = "MEX"
    if sito == "Google Flights":
        params = {
            'hl': 'it',
            'gl': 'it',
        }
        base = "https://www.google.com/travel/flights"
        fragment = f"#flt={origin}.{destination}.{partenza}*{destination}.{origin}.{ritorno};c:EUR;e:1;sd:1;tt:o"
        return f"{base}?{urlencode(params)}{fragment}"
    if sito == "Skyscanner":
        return (
            f"https://www.skyscanner.it/trasporti/voli/"
            f"{origin.lower()}/{destination.lower()}/{partenza.replace('-', '')}/"
            f"{ritorno.replace('-', '')}/?adults={num_passeggeri}&currency=EUR"
        )
    if sito == "Kayak":
        return (
            f"https://www.kayak.it/flights/{origin}-{destination}/"
            f"{partenza}/{ritorno}?adults={num_passeggeri}&c=EUR"
        )
    if sito == "Aeromexico":
        return (
            "https://aeromexico.com/en-us/search?"
            + urlencode({
                'tripType': 'roundTrip',
                'adults': num_passeggeri,
                'children': 0,
                'infants': 0,
                'origin': origin,
                'destination': destination,
                'departureDate': partenza,
                'returnDate': ritorno,
                'cabin': 'ECONOMY',
            })
        )
    return "https://www.google.com/travel/flights"

def main():
    """Funzione principale"""
    
    print("🚀 Avvio Flight Monitor FCO-MEX (Aeromexico Diretto)")
    print(f"📅 Date: {PARTENZA} → {RITORNO}")
    print(f"👥 Passeggeri: {NUMERO_PASSEGGERI}")
    print(f"🎯 Target: €{PREZZO_SOGLIA} | Buono: €{PREZZO_BUONO}")
    print(f"🔔 Notifiche: {'Telegram' if USA_TELEGRAM else 'Email'}")
    print("-" * 50)
    
    # Controlla configurazione
    if not controlla_configurazione():
        return
    
    # Esegui controllo prezzi
    controlla_prezzi()
    
    # Ascolta comandi Telegram per richieste manuali (opzionale)
    if USA_TELEGRAM and ASCOLTA_COMANDI_TELEGRAM:
        print("\n🛰️ Ascolto comandi Telegram attivo (/prezzi)...")
        last_update_id = None
        while True:
            updates = leggi_messaggi_telegram(offset=last_update_id + 1 if last_update_id else None)
            if not updates or not updates.get('ok'):
                continue
            for upd in updates.get('result', []):
                last_update_id = upd.get('update_id', last_update_id)
                msg = upd.get('message') or upd.get('edited_message')
                if not msg:
                    continue
                chat_id = str(msg.get('chat', {}).get('id'))
                text = msg.get('text', '')
                if TELEGRAM_CHAT_ID and str(TELEGRAM_CHAT_ID) != chat_id:
                    # ignora altre chat
                    continue
                risposta = gestisci_comando_telegram(text)
                if risposta:
                    invia_messaggio_telegram(risposta)
    
    print("\n✅ Controllo completato!")
    print(f"📊 Prossimo controllo: manuale o automatico via scheduler")

if __name__ == "__main__":
    main()


