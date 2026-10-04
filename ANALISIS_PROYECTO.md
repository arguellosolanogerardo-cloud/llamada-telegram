# 📋 Análisis del Proyecto: Bot de Llamadas Telegram

> Documento generado el 3 de octubre de 2026

---

## ⚠️ El Problema Principal

Este bot **no es una app que se ejecuta una vez y ya**. Es una **automatización que corre en horarios programados 24/7**:
- Abrir sala de voz a las 7:56 PM diariamente
- Cerrar sala después de 5 horas si hay < 5 usuarios
- Limpieza periódica del grupo

Un `.exe` en Windows **solo funcionaría si la PC del usuario está encendida 24/7**, lo cual no es práctico.

---

## 📊 Opciones de Distribución

| Opción | Ventaja | Desventaja |
|---|---|---|
| **A. Asistente de configuración (.exe)** | Automatiza todo el setup de GitHub + cron-job.org | El usuario necesita cuenta GitHub |
| **B. Web App (SaaS)** | El usuario solo llena un formulario y listo | Requiere hosting (costo mensual) |
| **C. App de escritorio con tray icon** | Familiar para el usuario | PC debe estar encendida 24/7 |
| **D. Bot de Telegram que configura todo** | No necesita instalar nada | Más complejo de desarrollar |

---

## 📱 Visión Seleccionada: App Android + Bot de Telegram

```
┌──────────────────────────────────────────────────┐
│            FLUJO DEL USUARIO FINAL               │
│                                                  │
│  1. Instala la App Android desde Play Store      │
│  2. Agrega el Bot al grupo de Telegram           │
│  3. Escribe /setup en el grupo                   │
│  4. El Bot guía la configuración paso a paso     │
│  5. La App muestra dashboard de control          │
│  6. Todo corre en la nube automáticamente        │
└──────────────────────────────────────────────────┘
```

### 🏗️ Arquitectura Necesaria

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  App Android    │────▶│  Backend (API)   │◀────│  Bot Telegram   │
│  (Flutter)      │     │  (Cloud Server)  │     │  (Python)       │
│                 │     │                  │     │                 │
│ • Dashboard     │     │ • Base de datos  │     │ • /setup        │
│ • Config grupo  │     │ • Scheduler      │     │ • /status       │
│ • Estadísticas  │     │ • Abrir/Cerrar   │     │ • /config       │
│ • On/Off        │     │   salas de voz   │     │ • /limpieza     │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

### 💰 Costos Estimados del Backend

| Servicio | Costo |
|---|---|
| **VPS básico** (DigitalOcean/Hetzner) | $4-6 USD/mes |
| **Firebase** (si usas Spark gratuito) | $0 hasta cierto límite |
| **Railway/Render** (tier gratuito) | $0 (con límites) |

### ⚡ Componentes a Construir

1. **Bot de Telegram (Python)** → Recibe comandos `/setup`, `/status`, gestiona configuraciones
2. **Backend/API (Python FastAPI)** → Ejecuta las tareas programadas para TODOS los usuarios
3. **Base de datos (Firebase/PostgreSQL)** → Guarda configuración de cada usuario/grupo
4. **App Android (Flutter)** → Dashboard visual para gestionar todo

---

## 📊 Análisis de Mercado: Bot Automático de Salas de Voz en Telegram

### 🎯 Hallazgo Clave: TIENES UN NICHO ÚNICO

> **NO EXISTE ninguna app ni bot que abra automáticamente un chat de voz en Telegram.**
> Tu código hace algo que la industria considera "imposible" porque:
> - La API oficial de Bots de Telegram **NO permite** controlar chats de voz
> - La función nativa de "Programar chat de voz" **requiere que un admin pulse "Iniciar" manualmente**
> - Tú lo lograste usando **Telethon + MTProto (API de usuario)**, no la API de bots

### 🏆 Ventaja Competitiva

| Característica | Telegram Nativo | Bots existentes (Rose, Combot, etc.) | **Tu solución** |
|---|:---:|:---:|:---:|
| Abrir sala de voz automáticamente | ❌ | ❌ | ✅ |
| Cerrar sala si hay pocos usuarios | ❌ | ❌ | ✅ |
| Enviar aviso cuando abre la sala | ❌ | ⚠️ (solo texto) | ✅ |
| Limpieza automática de spam/stickers | ❌ | ✅ (parcial) | ✅ |
| Sin necesidad de admin presente | ❌ | ❌ | ✅ |
| Horario 100% puntual | ❌ | ❌ | ✅ |

### 👥 Público Objetivo

- Comunidades de estudio (ej: grupos de inglés, programación, biblia)
- Podcasters con sesiones diarias en Telegram
- Empresas con reuniones diarias de equipo
- Grupos de meditación / oración / lectura
- Comunidades gaming con horarios fijos
- Coaches y mentores con sesiones grupales

### 💰 Modelo de Negocio Sugerido (Freemium)

| Plan | Precio | Incluye |
|---|---|---|
| **Gratis** | $0 | 1 grupo, 1 horario, sin limpieza |
| **Pro** | $4.99 USD/mes | 3 grupos, horarios ilimitados, limpieza, cierre automático |
| **Business** | $14.99 USD/mes | Grupos ilimitados, analytics, soporte prioritario |

### 📈 Estimación de Ingresos

- 100 usuarios Pro = **$499 USD/mes**
- 50 usuarios Business = **$749 USD/mes**
- **Total estimado con tracción moderada: $1,200+ USD/mes**

### ⚠️ Riesgos a Considerar

1. **Términos de Telegram:** Usar la API de usuario (MTProto/Telethon) con cuentas de usuario está en zona gris. Telegram podría limitar o banear cuentas que automaticen acciones masivas.
2. **Escalabilidad:** Cada grupo necesita una sesión de usuario con permisos de admin. No es como un bot normal que agregas y ya.
3. **Competencia futura:** Telegram podría agregar esta funcionalidad nativa.

### ✅ Estrategia Recomendada

1. Lanzar primero como **Bot de Telegram** (sin app, más rápido de desarrollar)
2. Validar con 20-50 usuarios gratuitos
3. Si hay tracción, construir la **App Android** con dashboard
4. Monetizar con suscripción mensual

### 🗓️ Roadmap de Desarrollo

```
Fase 1 (2-3 semanas): Bot de Telegram con /setup
Fase 2 (1-2 semanas): Dashboard web simple
Fase 3 (3-4 semanas): App Android (Flutter)
Fase 4 (continuo):    Marketing y crecimiento
```

---

## 🔧 Problema Resuelto: Puntualidad del Cron de GitHub Actions

### Causa
Los eventos `schedule` (cron) de GitHub Actions no corren con precisión de reloj. GitHub los encola en servidores compartidos, causando demoras de **5 a 30+ minutos**.

### Solución Implementada: cron-job.org
Se configuró un disparador externo gratuito en [cron-job.org](https://cron-job.org/) que envía un `workflow_dispatch` a la API de GitHub a las **7:56:00 PM exactas (hora Colombia)**.

#### Configuración:
- **URL:** `https://api.github.com/repos/arguellosolanogerardo-cloud/llamada-telegram/actions/workflows/llamada.yml/dispatches`
- **Método:** `POST`
- **Headers:**
  - `Authorization: Bearer <GITHUB_TOKEN>`
  - `Accept: application/vnd.github.v3+json`
  - `User-Agent: CronJob`
- **Body:** `{"ref":"main"}`
- **Zona horaria:** `America/Bogota`
- **Horario:** Todos los días a las `19:56`

#### Resultado de prueba:
- ✅ Chat de voz creado exitosamente
- ✅ Aviso del bot enviado (HTTP 200)
- ✅ Ejecución en ~16 segundos
