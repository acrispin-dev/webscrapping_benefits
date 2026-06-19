import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import date

from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
REMITENTE = "alvarocrispin0604@gmail.com"
DESTINATARIO = "alvaroecrispin@yape.com.pe"


def enviar_csv_por_correo(ruta_csv: str) -> None:
    """Envía el archivo CSV como adjunto al destinatario configurado."""
    app_password = os.getenv("GMAIL_APP_PASSWORD")
    if not app_password:
        raise EnvironmentError(
            "Falta la variable GMAIL_APP_PASSWORD en el archivo .env. "
            "Genera una contraseña de aplicación en: "
            "https://myaccount.google.com/apppasswords"
        )

    if not os.path.exists(ruta_csv):
        raise FileNotFoundError(f"No se encontró el CSV a enviar: {ruta_csv}")

    fecha_hoy = date.today().strftime("%d/%m/%Y")
    nombre_archivo = os.path.basename(ruta_csv)

    msg = MIMEMultipart()
    msg["From"] = REMITENTE
    msg["To"] = DESTINATARIO
    msg["Subject"] = f"Promociones Yape — {fecha_hoy}"

    cuerpo = (
        f"Hola,\n\n"
        f"Adjunto encontrarás el archivo <b>{nombre_archivo}</b> con las promociones "
        f"obtenidas el {fecha_hoy}.\n\n"
        f"Saludos."
    )
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

    with open(ruta_csv, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{nombre_archivo}"')
    msg.attach(part)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(REMITENTE, app_password)
        server.sendmail(REMITENTE, DESTINATARIO, msg.as_string())

    print(f"✅ Correo enviado a {DESTINATARIO} con adjunto: {nombre_archivo}")
