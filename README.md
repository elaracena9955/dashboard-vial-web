# Dashboard Vial IA

Tablero web de solo lectura para visualizar las detecciones de baches y sus evidencias guardadas en Supabase. La detección con IA se ejecuta en el computador del vehículo; este tablero presenta los datos recibidos.

## Archivos

- `app.py`: aplicación del tablero.
- `requirements.txt`: bibliotecas necesarias.

## Ejecución local

Instala las dependencias con `pip install -r requirements.txt` y ejecuta `streamlit run app.py`.

## Configuración para publicar

En los secretos privados del servicio de alojamiento configura `SUPABASE_URL` y `SUPABASE_SECRET_KEY`. No pongas esos valores en este repositorio ni compartas la clave secreta.

El tablero es de solo lectura. Si se publica sin protección, cualquier persona con el enlace podrá ver los datos y evidencias que el tablero muestre.
