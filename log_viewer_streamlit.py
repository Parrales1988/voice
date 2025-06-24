import streamlit as st
import paramiko
import cx_Oracle
import re
import os
from datetime import datetime

# --- CONFIGURACIÓN BASE ---
ORACLE_HOST = "dlecd002.tia.com.ec"
ORACLE_PORT = 1521
ORACLE_SID = "WMS"
ORACLE_USER = "wms"
ORACLE_PASSWORD = "wmstia2020"

SSH_HOST = "alb-voicepicking.dev.aws.tia.com.ec"
SSH_PORT = 22

# --- CONEXIÓN SSH CON LLAVE PRIVADA ---
def conectar_ssh_con_llave(usuario, ruta_llave):
    try:
        key = paramiko.RSAKey.from_private_key_file(ruta_llave)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(SSH_HOST, port=SSH_PORT, username=usuario, pkey=key)
        return client
    except Exception as e:
        st.error(f"Error SSH con llave: {e}")
        return None

# --- CONEXIÓN ORACLE ---
def conectar_oracle():
    try:
        dsn = cx_Oracle.makedsn(ORACLE_HOST, ORACLE_PORT, sid=ORACLE_SID)
        conn = cx_Oracle.connect(user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=dsn)
        return conn
    except cx_Oracle.Error as e:
        st.error(f"Error Oracle: {e}")
        return None

# --- PROCESAR ARCHIVO LOG ---
def procesar_log(path, facility_id, conn):
    cur = conn.cursor()

    with open(path, 'r') as f:
        for line in f:
            match = re.match(r"(\d{4}\.\d{2}\.\d{2}) (\d{2}:\d{2}:\d{2}\.\d+)/(\w+)\s*;\s*(\w+)\s*;\s*\[(.*?)\]\s*(.*)", line)
            if match:
                fecha_str = match.group(1).replace('.', '-')
                hora = match.group(2)
                fecha_dt = datetime.strptime(f"{fecha_str} {hora}", "%Y-%m-%d %H:%M:%S.%f")

                program_name = match.group(3)
                type_program = match.group(4)
                action_program = match.group(5).strip()
                details = match.group(6).strip()

                cur.execute("""
                    INSERT INTO NB_LYDIA_LOG (facility_id, datetime, horatime, program_name, type_program, action_program, details, create_date)
                    VALUES (:1, :2, :3, :4, :5, :6, :7, :8)
                """, (
                    facility_id,
                    fecha_dt.date(),
                    fecha_dt,
                    program_name,
                    type_program,
                    action_program,
                    details,
                    datetime.now().date()
                ))

    conn.commit()
    cur.close()
    st.success(f"Procesado archivo: {path}")

# --- APP STREAMLIT ---
st.set_page_config(page_title="App Lydia", layout="centered")
st.title("🔐 App de Logs - Lydia")

menu = st.sidebar.selectbox("Menú", ["Login", "Log Lydia", "Sistemas"])

if "ssh" not in st.session_state:
    st.session_state.ssh = None

if menu == "Login":
    usuario = st.text_input("Usuario SSH", value="logis_ti_1")
    ruta_llave = st.text_input("Ruta a la llave privada (.pem)", value="C:/Voice/llave servidor voive/prd/jj_picking.pem")
    if st.button("Conectar con llave privada"):
        ssh = conectar_ssh_con_llave(usuario, ruta_llave)
        if ssh:
            st.success("Conexión SSH exitosa con llave")
            st.session_state.ssh = ssh
elif menu == "Log Lydia" and st.session_state.ssh:
    site = st.selectbox("Seleccione Site", ["Guayaquil", "Quito"])
    tipo = st.selectbox("Seleccione Tipo", ["Secos", "Frios"])

    folder_prefix = "PRD01" if tipo == "Secos" else "PRD02"
    ubicacion = f"{site}PRD"
    ruta_base = f"/opt/lydia/lydia-voice/sites/{ubicacion}/logs"

    try:
        sftp = st.session_state.ssh.open_sftp()
        sftp.chdir(ruta_base)
        carpetas = [f for f in sftp.listdir() if f.startswith(folder_prefix)]

        carpeta_sel = st.selectbox("Carpeta disponible", carpetas)
        if carpeta_sel:
            ruta_full = f"{ruta_base}/{carpeta_sel}"
            sftp.chdir(ruta_full)
            archivos = sftp.listdir()
            archivo_sel = st.selectbox("Archivo", archivos)
            if st.button("Descargar archivo"):
                local_path = f"./{archivo_sel}"
                sftp.get(archivo_sel, local_path)
                with open(local_path, 'rb') as f:
                    st.download_button("Descargar", f, file_name=archivo_sel)
    except Exception as e:
        st.error(str(e))
elif menu == "Sistemas" and st.session_state.ssh:
    clave_sistema = st.text_input("Clave acceso Sistemas", type="password")
    if clave_sistema == "clave123":
        st.success("Acceso concedido")

        site = st.selectbox("Procesar datos de site", ["Guayaquil", "Quito"])
        ubicacion = f"{site}PRD"
        ruta_logs = f"/opt/lydia/lydia-voice/sites/{ubicacion}/logs"

        if st.button("Procesar Logs"):
            conn_db = conectar_oracle()
            if conn_db:
                try:
                    sftp = st.session_state.ssh.open_sftp()
                    sftp.chdir(ruta_logs)
                    carpetas = sftp.listdir()

                    for carpeta in carpetas:
                        if carpeta.startswith("PRD01"):
                            facility_id = "01"
                        elif carpeta.startswith("PRD02"):
                            facility_id = "02"
                        else:
                            continue

                        ruta_carpeta = f"{ruta_logs}/{carpeta}"
                        sftp.chdir(ruta_carpeta)
                        archivos = sftp.listdir()

                        for archivo in archivos:
                            if not archivo.endswith(".log"):
                                continue
                            local_path = f"./{archivo}"
                            sftp.get(archivo, local_path)
                            procesar_log(local_path, facility_id, conn_db)
                            os.remove(local_path)
                    conn_db.close()
                except Exception as e:
                    st.error(str(e))
    else:
        st.warning("Clave incorrecta")
else:
    st.info("Por favor, inicie sesión desde el menú Login.")
