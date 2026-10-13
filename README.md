# cITA Browser 7.0 — Suite Fiscale, PDF Studio & Firma Digitale

![Licenza: GPLv3](https://img.shields.io/badge/Licenza-GPLv3-blue.svg)
![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-green.svg)
![Piattaforma: Windows | Linux](https://img.shields.io/badge/Piattaforma-Windows%20%7C%20Linux-lightgrey.svg)

**cITA Browser 7.0** è un'applicazione desktop libera, aperta e gratuita (FOSS), progettata per professionisti, aziende, commercialisti, tributaristi e consulenti.

Copyright (C) 2026 Francesco Ventura — Licenza GNU GPLv3 (vedi [LICENSE](LICENSE) e [AUTHORS](AUTHORS)).

Integra in un unico ambiente protetto:
1. **Navigazione Istituzionale & Automazione Fiscale (AdE, INPS, Portali PA)**:
   - **Navigazione Privata "Off-The-Record" perenne**: cronologia, cache HTTP e cookie di sessione risiedono esclusivamente in memoria RAM e vengono distrutti alla chiusura dell'applicazione. Nessuna traccia di credenziali, sessioni o file temporanei viene lasciata sul disco.
   - **Login con SPID, CIE e CNS**: gestione diretta dei certificati digitali client TLS (CIE 3.0 / Smart Card / Token) per l'accesso immediato e sicuro ai portali della Pubblica Amministrazione.
    - **Automazione Agenzia delle Entrate (AdE)**:
      - Download rapido (fino a 30 giorni) e richieste massive (fino a 90 giorni) di fatture elettroniche emesse e ricevute.
      - **Login automatico Fisconline/Entratel**: se la sessione AdE non è aperta, Veloce, Massive e Lista richieste entrano da sole con utente, password e PIN del profilo a cui appartiene la Partita IVA (il pulsante *Accedi* viene premuto al massimo una volta: nessun tentativo ripetuto che possa bloccare l'utenza). Funziona sia da non loggati sia a sessione già aperta; con password scaduta il login automatico non parte.
      - **Scelta automatica dell'utenza di lavoro (wizard AdE)**: la richiesta imposta da sola il soggetto giusto. Passando a un'altra Partita IVA, anche nella stessa sessione, il wizard viene ripetuto automaticamente; se non si apre, la sessione viene chiusa e riaperta con un nuovo login (come fa lo scheduler).
      - **Lista richieste massive in un passaggio**: si sceglie il soggetto, il programma fa login e wizard se servono, apre l'area richieste massive e mostra la lista con il pulsante *Scarica* per le richieste elaborate (fino a 3 tentativi automatici se il portale non è ancora pronto).
      - Supporto trasparente e universale a tutte le utenze di lavoro: **Accesso Diretto ("Me Stesso")**, **Incaricato di società** e **Intermediario con Delega Fiscale** (i cookie di autenticazione e i token di sessione vengono ereditati nativamente dal motore Chromium).
      - Intercettazione automatica dei token di sessione autenticata senza scraping non autorizzato.
      - Riconoscimento del limite giornaliero AdE sulle richieste massive e della "Partita IVA incongruente" (coda fermata, utenza reimpostata alla richiesta successiva).
      - Deduplica e gestione affidabile dei flussi (coda atomica a 96 ore).
2. **Archivio & Visualizzatore Fatture XML/p7m e Ricevute SDI**:
    - **Hub di Consultazione e Archivio Completo**:
      - Filtro istantaneo per Registro (Attive/Emesse, Passive/Ricevute o Tutte), Anno, Mese e Tipo Documento.
      - Ricerca rapida in tempo reale per Cliente/Fornitore, Denominazione o Partita IVA / Codice Fiscale.
      - Totali contabili calcolati al volo sulla selezione e sull'elenco filtrato.
    - **Download Mirato Ricevute SdI Ufficiali (RC / MC / NS / NE)**:
      - Pulsante dedicato **"📥 Scarica Ricevute SdI (RC/MC)"** e menu contestuale per scaricare puntualmente o in blocco le notifiche ministeriali delle fatture selezionate.
      - **Algoritmo di Ricerca a 5 giorni da Data Accoglienza**: interroga automaticamente il Monitoraggio AdE (`/ser/api/monitoraggio/v1/monitoraggio/fatture/`) impostando la finestra temporale da `Data Accoglienza - 1gg` a `Data Accoglienza + 5gg` (formato `MM/DD/YYYY`).
      - **Zero Download Ridondanti**: scarica unicamente i file XML originali delle ricevute SdI (`RicevutaConsegna_*.xml`, `NotificaMancataConsegna_*.xml`, `NotificaScarto_*.xml`), posizionandoli nella cartella del documento senza riscaricare duplicati di fatture o metadati già presenti.
    - **Badge di Stato Ministeriali & Accoppiamento Intelligente**:
      - I metadati e le ricevute SdI vengono agganciati automaticamente alla riga della rispettiva fattura tramite ID SdI, nome file o stem.
      - Visualizzazione immediata dello stato nella colonna dedicata:
        - `RC ✓` (Verde): **Ricevuta di Consegna** regolare rilasciata dal Sistema di Interscambio (SdI).
        - `MC ⚠️` (Ambra): **Notifica di Mancata Consegna** (fattura recapitata nel cassetto fiscale / messa a disposizione).
        - `NS ❌` (Rosso): **Notifica di Scarto** SdI.
        - `NE 📋` (Blu): **Notifica Esito Committente** (FatturaPA).
        - `ℹ` (Blu): **Metadati Ufficiali AdE** (`_meta.xml` / `informazioni_associate_*.xml` / `_MT_001.xml`) con popup interattivo per consultare ID SdI, Data Accoglienza e Hash.
    - **Stampa Multipla & Esportazione Massiva**:
     - **Stampa Multipla Unione**: genera con un click un unico documento PDF multipagina riordinato contenente tutte le fatture selezionate (con caselle di spunta rapide).
     - **Esportazione PDF Singoli**: conversione massiva di tutte le fatture selezionate in file `.pdf` distinti in una cartella a scelta.
     - **Esportazione Elenco Excel (`.xlsx`)**: foglio di calcolo formattato con intestazioni e riepilogo contabile pronto per l'importazione.
   - **Rendering Grafico Professionale FatturaPA**:
     - Layout chiaro e conforme alle specifiche Agenzia delle Entrate con identità visiva cITA (`#005CA8`, `#FFDF00`, `#F8FAFC`).
     - Supporto completo a Fatture Ordinarie (FPR12, FPA12), Semplificate (FSM10) e Ricevute SDI (RC, NS, MC, MT).
     - Sbustamento trasparente di file firmati digitalmente `.xml.p7m` con estrazione certificati e allegati in Base64.
3. **Smistamento Automatico Download & Archiviazione Ordinata**:
   - **Download Veloce (fino a 30 gg)**:
     - Fatture Emesse $\rightarrow$ `<Cartella_Output>/fatture/attive/`
     - Fatture Ricevute $\rightarrow$ `<Cartella_Output>/fatture/passive/`
   - **Richieste Massive (fino a 90 gg)**:
     - Archivio ZIP Fatture $\rightarrow$ `<Cartella_Output>/massive/fatture/`
     - Archivio ZIP Corrispettivi $\rightarrow$ `<Cartella_Output>/massive/corrispettivi/`
   - Gestione atomica locale trasparente in file JSON (`~/.cita_browser/`) senza database pesanti o proprietari.
4. **Suite PDF Studio Integrata**:
   - Visualizzatore PDF multi-scheda con strumenti di annotazione, evidenziazione e firma visuale.
   - **Conversione PDF in Microsoft Word (.docx)**: ricostruzione nativa e modificabile con preservazione accurata di layout, formattazione, font, tabelle e immagini.
   - **Conversione ed Estrazione PDF in Microsoft Excel (.xlsx)**: esportazione intelligente di tabelle, griglie, elenchi e prospetti contabili/fiscali in fogli di calcolo Excel nativi (su foglio singolo o suddiviso per pagina).
   - Unione (Merge), Divisione (Split) ed Estrazione pagine per intervalli o pagine singole.
   - Compressione PDF intelligente (Bilanciata/Massima) e normalizzazione compatibile PDF/A (conformità ISO **non certificata** — per archiviazione a norma usare un validatore dedicato come veraPDF).
   - Timbro e apposizione protocollo documentale con supporto a timbri QR code.
   - Integrazione OCR per rendere ricercabili documenti scansionati.
5. **Firma Digitale & Crittografia**:
   - Firma grafica e crittografica **PAdES (.pdf)** con supporto a marca temporale (TSA).
   - Firma in busta crittografica **CAdES-BES (.p7m)** conforme alle regole tecniche AgID.
   - Supporto hardware per Smart Card e Token USB PKCS#11 (Aruba, Bit4id, Namirial, InfoCert, Poste, ecc.).
   - Verifica crittografica e sbustamento automatico di file firmati `.p7m`.
   - Firma massiva (Batch) in parallelo di cartelle e documenti.
   - **Nota onestà verifica:** la funzione "Verifica" integrata è un'**ispezione dei firmatari** (catena, OCSP e revoche **non** verificate) — **senza valore probatorio**. Per valore legale usare verificatori qualificati (DSS UE, Aruba, InfoCert) o i portali ufficiali.
6. **Utility di Rete & IP Scanner Integrato**:
   - Scansione ultra-rapida della rete locale in parallelo multi-thread (50 worker).
   - Rilevamento automatico di stampanti e multifunzione di rete, router, NAS, server e PC.
   - Risoluzione Hostname, indirizzo MAC (tabella ARP) e Vendor del produttore.
   - Azione immediata **"Apri nel Browser cITA"** per accedere alle pagine web di configurazione dei dispositivi locali (porte 80, 443, 8080, ecc.).
   - Esportazione della mappa di rete in formato Excel (`.xlsx`) e CSV.
7. **Pannello Produttività (Agenda, To-Do & Blocco Note)**:
   - Dock laterale con **Agenda/Calendario** (scadenze fiscali e appuntamenti), **To-Do list** con promemoria e **Blocco Note** integrato.
   - Note salvate in `~/.cita_browser/note_salvate/` (migrazione automatica dalla vecchia cartella locale): nessun database proprietario, tutto ispezionabile.
   - Reminder con notifiche a timer senza lasciare il contesto di lavoro.
8. **Esperienza Browser Quotidiana**:
   - Multi-scheda con homepage configurabile, preferiti con credenziali nel **keyring OS** (mai in chiaro) e copia negli appunti con autocancellazione dopo 30 secondi.
   - Profili AdE multipli (Accesso Diretto, Incaricato, Intermediario con Delega), ciascuno con i propri soggetti (Partita IVA / CF) e le credenziali usate dal login automatico, con avviso di scadenza password.
   - Single-instance: un secondo avvio inoltra l'URL all'istanza già aperta invece di duplicarla.
   - Certificati client TLS (CIE 3.0 / CNS / Smart Card) per login SPID/CIE/CNS ai portali PA.
   - Tasti rapidi e menu contestuale rapido per download, richieste AdE e cambio cartella output.

---

## 💻 Requisiti di Sistema

| Requisito | Windows | Linux |
|---|---|---|
| OS | Windows 10 / 11 / Server 64-bit | Debian / Ubuntu / Linux Mint |
| Python | **3.11 auto-installato** da `installa.bat` (winget → python.org, zero-click) | `python3.11+`, `python3-venv`, `python3-pip` (auto via apt se sudo) |
| Spazio | ~800 MB per `.venv` + dipendenze | idem |
| Rete | Connessione per download installer/dipendenze | idem |
| Extra | Driver PKCS#11 del fornitore per Smart Card/Token (non inclusi) | `libqpdf` (pikepdf), `pcscd` (smart card), `gnome-keyring` (keyring) |

> La disinstallazione **non** rimuove Python di sistema né i dati in `~/.cita_browser/` (restano tuoi).

---

## 🏗️ Build Standalone (EXE Windows)

1. Installa prima l'ambiente con `installa.bat` (crea `.venv` con le dipendenze pinnate in `requirements.txt`).
2. Installa gli strumenti di build: `.venv\Scripts\python.exe -m pip install -r requirements-build.txt`.
3. Esegui `build.bat` → l'eseguibile è in `dist\cITA_Browser_7.0\`.
4. Alla prima esecuzione Windows SmartScreen può mostrare "Windows ha protetto il PC": *Ulteriori informazioni → Esegui comunque* (build non firmata con certificato commerciale).

---

## 🔐 Privacy & Dati Locali

* Nessun dato lascia il PC: l'app parla solo con i portali che visiti (AdE, INPS, PA).
* Configurazione e stato operativo in `~/.cita_browser/` (`preferiti.json`, `profiles.json`, code download): nessun database pesante o proprietario. La disinstallazione **non** cancella questa cartella (i tuoi dati restano tuoi).
* Password dei preferiti: custodite nel **keyring del sistema operativo**, mai in chiaro su disco; copia negli appunti con cancellazione automatica dopo 30 secondi. La disinstallazione (`disinstalla.bat/.sh`) offre la rimozione delle credenziali dal keyring.
* Credenziali dei **Profili AdE** (utente, password, PIN usati dal login automatico): salvate **in chiaro** nel file locale `~/.cita_browser/profiles.json`, leggibile da chi accede al tuo account del PC. Proteggi l'account con una password e non copiare quel file altrove; se preferisci, lascia vuoti password e PIN e accedi a mano (il login automatico semplicemente non parte).
* Token di sessione AdE solo in RAM e troncati nei log (`prime 16 cifre`).

---

## 🧰 Requisiti Opzionali

* **OCR**: richiede `ocrmypdf` e/o `Tesseract` installati nel sistema; in mancanza, l'app elabora i PDF con testo incorporato e avvisa per le scansioni.
* **PDF/A a norma**: la funzione integrata è una normalizzazione compatibile **non certificata**; per conservazione a norma validare con `veraPDF` o Ghostscript.
* **Token USB / Smart Card**: driver PKCS#11 del fornitore (Aruba, Bit4id, InfoCert, Namirial, Poste, CIE...); nessun driver incluso nel repo.

---

## ⚠️ Disclaimer Fiscale & Legale

cITA Browser 7.0 è uno strumento tecnico **senza garanzia** (GPLv3 §15-16): **non è consulenza fiscale, tributaria o legale**. Verificare sempre esiti, scadenze e adempimenti sui portali ufficiali (Agenzia delle Entrate, INPS) o con il proprio commercialista/consulente. L'uso è a proprio rischio; gli autori non rispondono di errori, omissioni o sanzioni derivanti dall'uso.

---

## 🔒 Privacy, Sicurezza & Gestione CIE / Smart Card

### 🛡️ Modalità Navigazione Privata (Off-The-Record)
Il motore del browser (QtWebEngine/Chromium) è configurato nativamente in modalità **Off-The-Record**:
* **Zero residui su disco:** Non vengono scritti file di cache, database IndexedDB o cookie persistenti nella cartella dell'utente.
* **Sessioni isolate:** Ogni riavvio del browser offre un ambiente pulito, prevenendo conflitti di vecchi cookie o problemi di "cache sporca" sui portali istituzionali.
* **Sicurezza su PC condivisi:** Alla chiusura dell'app, tutte le sessioni aperte decadono istantaneamente.

### 🪪 Autenticazione CIE vs Firma Digitale
* **Login Web (Autenticazione Livello 3):** La Carta d'Identità Elettronica (CIE 3.0) opera nativamente per l'accesso ai siti istituzionali (INPS, AdE, ecc.) tramite handshake client TLS a livello di sistema operativo.
* **Firma Documentale:** Per la firma con valore di Firma Elettronica Avanzata (FEA) tramite CIE, si raccomanda l'uso dell'app ufficiale *CIE ID* (Poligrafico dello Stato). Per apporre firme con valore di Firma Digitale Qualificata (FEQ), utilizzare token/smart card rilasciate dai Certificatori Accreditati AgID.

### ⚠️ Avviso: Ricerche Google & Verifiche CAPTCHA ("Unusual Traffic")
Poiché cITA Browser opera rigorosamente **senza cookie persistenti su disco** (`NoPersistentCookies`) per garantire la totale riservatezza e azzerare ogni traccia locale, i sistemi anti-bot di Google possono presentare occasionalmente la schermata:
> *"Our systems have detected unusual traffic from your computer network..."*

* **Perché accade:** Google assegna ai browser un punteggio di reputazione basato su cookie di lungo termine (es. `NID`, `AEC`). In assenza di cookie persistenti (oppure se si utilizzano VPN, proxy o connessioni con IP condiviso CGNAT/hotspot), Google non trova uno storico fidato e richiede la verifica interattiva.
* **Come comportarsi:** È sufficiente risolvere la verifica CAPTCHA visualizzata a video. Il token di sblocco rimarrà valido in memoria RAM per l'intera durata della sessione di navigazione corrente.
* **Alternative:** Per evitare controlli anti-bot frequenti, è possibile effettuare le ricerche web su motori orientati alla riservatezza (come [DuckDuckGo](https://duckduckgo.com) o [Startpage](https://www.startpage.com)).

---

## 🚀 Installazione & Avvio Rapido

### 🪟 Su Windows (10 / 11 / Server)
1. Fai doppio clic su **`installa.bat`** — **non devi installare nulla a mano**:
   - Se Python 3.11 manca, viene installato da solo (prima via `winget`, altrimenti scaricando l'installer ufficiale 3.11.9 da python.org).
   - Crea l'ambiente isolato `.venv`, aggiorna `pip` e installa tutte le librerie pinnate in `requirements.txt`.
   - Crea l'icona sul Desktop **"cITA Browser 7.0"** e nel Menu Start (nessuna associazione predefinita forzata).
2. Per avviare: fai doppio clic sull'icona sul Desktop oppure su **`avvia_browser.bat`** (avvio istantaneo e silenzioso, senza finestra di terminale; se `.venv` manca, parte da solo `installa.bat`).
3. Per aggiornare un'installazione esistente: usa **`aggiorna.bat`** con lo ZIP della nuova versione (anche lo ZIP scaricato da GitHub con *Code → Download ZIP*):
   - trascina lo ZIP sopra `aggiorna.bat`, **oppure** mettilo nella cartella del programma e fai doppio clic su `aggiorna.bat` (prende lo ZIP più recente), **oppure** fai doppio clic e sceglilo dalla finestra;
   - lo script chiude cITA Browser (dopo averti chiesto di salvare), salva una copia dei file attuali in `backup_aggiornamenti\<data_ora>\`, copia i file nuovi, aggiorna le librerie solo se `requirements.txt` è cambiato e riavvia il programma;
   - restano intatti `.venv`, le note e i dati in `~/.cita_browser/` (profili, preferiti, configurazione). Per tornare indietro basta ricopiare i file dal backup.
4. Per disinstallare: fai doppio clic su **`disinstalla.bat`** (chiude il programma, rimuove collegamenti e chiavi di Registro; chiede se rimuovere anche credenziali keyring e `.venv`; i dati in `~/.cita_browser/` restano conservati).

### 🐧 Su Linux Debian / Ubuntu / Linux Mint
1. Apri il terminale nella cartella del programma ed esegui:
   ```bash
   chmod +x installa.sh avvia_browser.sh disinstalla.sh
   ./installa.sh
   ```
2. Lo script verifica Python 3.11+ (tenta `apt install` automatico se hai `sudo`), crea `.venv`, aggiorna `pip`, installa le dipendenze e configura il lanciatore `.desktop` nel menu di sistema.
3. Per avviare: `./avvia_browser.sh` (o dal menu Applicazioni).
4. Per disinstallare: `./disinstalla.sh` (rimuove i lanciatori e aggiorna il database desktop; chiede se rimuovere keyring e `.venv`; `~/.cita_browser/` conservata).

---

## 📁 Struttura Repository (per upload manuale su GitHub)

```
cITA_Browser_7.0/
├── cita_browser.py          # entry-point applicativo
├── modules/                 # browser, AdE, PDF, firma, rete, produttivita
├── assets/                  # icone e risorse (incluse nel repo)
├── installa.bat / .sh       # installer zero-click / guidato
├── avvia_browser.bat / .sh  # avviatori rapidi
├── aggiorna.bat             # aggiornamento da ZIP con backup (Windows)
├── disinstalla.bat / .sh    # rimozione pulita
├── associa_*.bat / rimuovi_*.bat  # ruoli Windows opzionali (Browser/PDF/XML)
├── requirements.txt         # dipendenze runtime pinnate
├── requirements-build.txt   # solo build EXE (pyinstaller)
├── build.bat + cITA_Browser_7.0.spec  # build standalone
├── LICENSE / AUTHORS / README.md / .gitignore
└── .venv/ dist/ build/ note_salvate/ backup_aggiornamenti/  # ESCLUSI dal repo (vedi .gitignore)
```

Caricamento manuale: crea un repo vuoto su GitHub, poi da questa cartella `git init && git add . && git commit && git remote add origin <url> && git push -u origin main`. Il `.gitignore` esclude già `.venv/`, `dist/`, dati utente e file reali (`.p7m`, `.har`, fatture).

---

## ⚖️ Licenza Libera (GNU GPLv3) — Gratuito per Sempre

Copyright (C) 2026 Francesco Ventura. Rilasciato sotto **GNU General Public License v3.0 (GPLv3)**.

* **Gratuito al 100%**: Libero e gratuito per qualsiasi scopo, incluso l'uso professionale e commerciale in studi e aziende.
* **Aperto e Trasparente**: Libertà totale di ispezione, esecuzione, modifica e ridistribuita del codice sorgente.
* **Copyleft Forte**: Eventuali opere derivate devono rimanere libere e open-source con la medesima licenza GPLv3.

Consulta il file [LICENSE](LICENSE) per i termini legali completi.
