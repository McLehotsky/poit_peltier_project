# Dokumentácia k inštalácii a spusteniu projektu

Tento návod vás prevedie krokmi potrebnými na naklonovanie repozitára a úspešné spustenie aplikácie poit_peltier_project na systéme Windows.

1. KLONOVANIE PROJEKTU
Otvorte terminál v novom folderi a zadajte:
git clone https://github.com/McLehotsky/poit_peltier_project.git

2. PRÍPRAVA (ideálne vo VS Code)
Otvorte projekt a v termináli zadajte:
py -m venv venv

3. WINDOWS FIX (ak nefunguje aktivácia)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned

4. AKTIVÁCIA VIRTUÁLNEHO PROSTREDIA
.\venv\Scripts\activate

5. INŠTALÁCIA REQUIREMENTS
pip install -r requirements.txt

6. SPUSTENIE APP
cd .\server\
python app.py
