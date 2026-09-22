# ScribeDesk

[Français](../README.md) · [English](README.en.md) · **Español**

**Un asistente de escritura de escritorio para centros de soporte informático —
que nunca envía los datos de sus usuarios.**

Seleccione texto en cualquier aplicación, pulse `Ctrl+Espacio` y elija una
acción. O pulse `Ctrl+Alt+Espacio`: la corrección reemplaza su selección sin
mostrar nada en pantalla.

Lo que lo distingue cabe en una frase: **los datos personales se sustituyen por
fichas antes de llamar al modelo, y los valores reales se reinyectan en la
respuesta.** El proveedor en la nube nunca ve el nombre del usuario; usted
recupera un texto completo y listo para pegar.

<p align="center">
  <img src="quick-action.gif" alt="El gesto rápido Ctrl+Alt+Espacio" width="100%">
</p>

## El problema

Un agente de soporte escribe todo el día notas llenas de datos personales:
nombres, números de teléfono, direcciones, identificadores de conexión. Darle un
asistente conectado a una API estadounidense significa exportar esos datos fuera
de la Unión Europea cada vez que se corrige una falta de ortografía.

Las dos respuestas habituales no satisfacen: prohibir la herramienta — y el
agente sigue escribiendo mal, o abre ChatGPT en el navegador sin ninguna
protección — o alojarlo todo en local, caro y a menudo fuera del alcance de un
servicio pequeño.

ScribeDesk propone una tercera vía.

## Cómo funciona

<p align="center">
  <img src="architecture.svg" alt="Arquitectura y flujo de datos de ScribeDesk" width="100%">
</p>

El proveedor recibe una frase gramaticalmente completa — y por eso puede
corregirla bien — pero vaciada de todo dato identificativo. `SAP` sigue visible:
es el nombre de una aplicación, no un dato personal, y el modelo lo necesita
para entender el contexto.

## Pruébelo en treinta segundos

Sin clave de API, sin cuenta, sin conexión de red:

```bash
git clone https://github.com/Geniiius/scribedesk
cd scribedesk
pip install -e .

scribedesk redact --mapping -t "Llamar a DUPONT al 02 000 00 00, ya no puede abrir SAP.
Correo: jean.martin@ejemplo.test"
```

El texto anonimizado sale por la salida estándar y la tabla de correspondencias
por la salida de error: `scribedesk redact -t "…" | …` solo transmite el texto,
nunca los valores reales.

## Instalación

### Windows — ejecutable autónomo

[**Descargar la última versión**](https://github.com/Geniiius/scribedesk/releases/latest)
— un único archivo `ScribeDesk.exe`, sin Python y sin instalación. Colóquelo
donde quiera y ejecútelo: aparece un icono en el área de notificación.

El ejecutable lo construye la integración continua a partir del código de este
repositorio y se publica con su huella SHA-256. Para verificar la descarga:

```powershell
Get-FileHash ScribeDesk.exe -Algorithm SHA256
```

No está firmado con ningún certificado, así que SmartScreen avisa en el primer
arranque — «Más información», luego «Ejecutar de todas formas».

### Desde el código fuente — Windows, Linux

Requiere **Python 3.11 o posterior**. Todavía no está publicado en PyPI.

```bash
git clone https://github.com/Geniiius/scribedesk
cd scribedesk

pip install -e .          # biblioteca y línea de comandos, sin dependencia Qt
pip install -e ".[gui]"   # con interfaz gráfica y atajos globales

python -m scribedesk
```

Probado en **Windows 11** y **Linux**. macOS no está soportado: los permisos de
accesibilidad y la firma del binario exigen un trabajo específico que no se ha
hecho.

## Elegir un modelo

ScribeDesk no incluye ningún modelo. Por defecto apunta a **Ollama en local** —
nada sale del equipo, y la anonimización pasa a ser superflua. Para un uso en
línea, elija un proveedor en Preferencias → Modelo. La clave se guarda en el
llavero del sistema operativo, nunca en un archivo.

| Proveedor | Particularidad |
|---|---|
| **Ollama** | Local, ningún dato sale, sin clave |
| **NVIDIA NIM** | Créditos gratuitos, amplia oferta de modelos |
| **Groq** | Muy rápido, plan gratuito generoso |
| **Mistral** | Alojamiento europeo |
| **OpenAI** | — |
| *Personalizado* | Cualquier punto de acceso compatible con OpenAI |

## Idioma

**La interfaz y las once acciones incluidas están escritas en francés.** Las
*respuestas* del asistente, en cambio, no lo están: en
Preferencias → Idioma del asistente, elija `Automático` (seguir el idioma del
texto seleccionado), `Français`, `English` o `Español`. Un idioma elegido desde
la paleta tiene prioridad sobre ese ajuste para un envío concreto.

La detección del idioma de origen cubre francés, inglés y español.

## Los dos atajos

| Atajo | Efecto |
|---|---|
| `Ctrl+Espacio` | Abre la paleta: 10 acciones, instrucción libre, historial, editor |
| `Ctrl+Alt+Espacio` | Aplica la acción por defecto y reemplaza la selección |

El segundo existe porque un registro de uso real mostró que **9 de cada 10
llamadas** usaban la misma acción, sobre textos de 80 caracteres de mediana.
Pasar por la paleta y luego por una ventana de resultado para corregir un acento
costaba seis gestos; este cuesta uno.

## Qué detecta

| Regla | Contenido | Fiabilidad |
|---|---|---|
| `EMAIL` | Direcciones de correo | Alta |
| `IBAN` | Cuentas bancarias | Alta — dígito de control mod 97 verificado |
| `NRN` | Registro nacional belga | Alta — dígito de control verificado |
| `NIR` | Seguridad social francesa | Alta — dígito de control verificado |
| `CB` | Tarjetas bancarias | Alta — algoritmo de Luhn |
| `TEL` | Teléfonos BE / FR / LU | Alta |
| `IP`, `MAC` | Direcciones de red | Alta |
| `URL` | Enlaces, a menudo con fichas | Alta |
| `LOGIN` | `DOMINIO\usuario` | Alta |
| `UID` | Identificadores tipo `dupontj01` | Media — heurística |
| `NOM` | Apellidos | **Media — heurística** |

Las reglas con dígito de control casi no producen falsos positivos: un número de
once cifras solo es un registro nacional si su clave cuadra.

**La detección de apellidos es distinta, y hay que decirlo con claridad:** se
basa en heurísticas — palabra en mayúsculas, palabra que sigue a un tratamiento
— filtradas por una lista de 200 siglas profesionales y palabras francesas
corrientes. Atrapa `DUPONT` y `M. Martin`, y deja pasar `SAP`, `RGPD` y
`BONJOUR` — pero **no sustituye a una relectura humana**. Un nombre escrito en
minúsculas en mitad de una frase se le escapa.

## Límites conocidos

- La detección de apellidos es heurística, como se explica arriba.
- La captura de la selección simula `Ctrl+C`. Una aplicación que bloquee ese
  atajo no proporcionará nada.
- macOS no está soportado.
- Un atajo global puede ser rechazado si ya está ocupado. ScribeDesk lo registra
  y sigue siendo utilizable desde el área de notificación.

## Seguridad

Un dato personal que cruza la frontera de red cuando una regla debería haberlo
enmascarado es una vulnerabilidad, y se comunica en privado — no en una
incidencia pública. Véase [`SECURITY.md`](../SECURITY.md).

## Licencia

**MIT**. Véase [`LICENSE`](../LICENSE).

---

Esta página es una traducción condensada. La
[documentación completa está en francés](../README.md) y cubre la escritura de
acciones propias, la arquitectura, las variables de entorno y el flujo de
desarrollo.
