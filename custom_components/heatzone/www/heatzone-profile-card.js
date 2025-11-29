import {
  LitElement,
  html,
  css,
} from "https://unpkg.com/lit-element@2.5.1/lit-element.js?module";

// Konstanten für die Höhen
const FRONT_CARD_HEIGHT = 1019;
const BACK_CARD_HEIGHT = 691;

// MQTT Client using Paho MQTT
class MQTTClient {
  constructor(config, onMessage) {
    this.config = config;
    this.onMessage = onMessage;
    this.client = null;
    this.connected = false;
    this.isInitialized = false;
    this.subscribedTopics = [];
    this._configReady = false;

    // Topics als Property
    this.topics = [
      "Temp1",
      "Temp2",
      "Temp3",
      "Temp4",
      "TempAway",
      "TempHoliday",
      "Activated",
      "Day1",
      "Day2",
      "Day3",
      "Day4",
      "Day5",
      "Day6",
      "Day7",
    ];
  }

  async connect() {
    return new Promise((resolve, reject) => {
      try {
        const clientId = `ha-heating-${Math.random().toString(16).substr(2, 8)}`;
        this.client = new Paho.Client(
          this.config.mqtt_host,
          Number(this.config.mqtt_port),
          clientId
        );

        this.client.onConnectionLost = (responseObject) => {
          if (responseObject.errorCode !== 0 && this.connected) {
            console.log("[MQTT] Connection Lost:", responseObject.errorMessage);
            this.connected = false;
          }
        };

        this.client.onMessageArrived = (message) => {
          if (this.onMessage) {
            this.onMessage(message.destinationName, message.payloadString);
          }
        };

        const connectOptions = {
          onSuccess: () => {
            //console.log("[MQTT] Connected");
            this.connected = true;
            this.subscribeToTopics();
            resolve();
          },
          onFailure: (err) => {
            console.error("[MQTT] Connection Failed:", err);
            reject(err);
          },
          userName: this.config.mqtt_user,
          password: this.config.mqtt_password,
          useSSL: false,
        };

        this.client.connect(connectOptions);
      } catch (err) {
        reject(err);
      }
    });
  }

  subscribeToTopics() {
    if (!this.client || !this.client.isConnected()) {
      console.warn('[MQTT] Cannot subscribe - client not connected');
      return;
    }

    this.subscribedTopics = [];

    this.topics.forEach((subtopic) => {
      const fullTopic = `${this.config.topic}/${subtopic}`;
      try {
        this.client.subscribe(fullTopic);
        this.subscribedTopics.push(fullTopic);
      } catch (e) {
        console.error(`[MQTT] Failed to subscribe to ${fullTopic}:`, e);
      }
    });
  }


  unsubscribeFromTopics() {
    if (!this.client || !this.client.isConnected()) {
      return;
    }

    if (this.subscribedTopics && this.subscribedTopics.length > 0) {
      this.subscribedTopics.forEach((topic) => {
        try {
          this.client.unsubscribe(topic);
          // console.log("[MQTT] Unsubscribed from:", topic);
        } catch (e) {
          console.error(`[MQTT] Failed to unsubscribe from ${topic}:`, e);
        }
      });
      this.subscribedTopics = [];
    }
  }

  publish(subtopic, payload) {
    if (!this.connected || !this.client) {
      console.warn("[MQTT] not connected");
      return;
    }

    // Topic wird aus config.topic + "/" + config.profile + "/" + subtopic zusammengesetzt
    const fullTopic = `${this.config.topic}/${subtopic}`;
    const message = new Paho.Message(JSON.stringify(payload));
    message.destinationName = fullTopic;
    message.retained = true;
    // console.log("[MQTT] Publishing to:", fullTopic, payload);
    this.client.send(message);
  }

  disconnect() {
    if (this.client && this.connected) {
      this.unsubscribeFromTopics();
      this.client.disconnect();
      this.connected = false;
    }
  }
}

// create json from vars
function matrixToJSON(matrix, temps, tempAway, tempHoliday, activated) {
  const result = {
    Temp1: temps[0],
    Temp2: temps[1],
    Temp3: temps[2],
    Temp4: temps[3],
    TempAway: tempAway,
    TempHoliday: tempHoliday,
    Activated: activated,
  };

  for (let day = 0; day < 7; day++) {
    const dayKey = `Day${day + 1}`;
    const intervals = matrix[day];
    const timeBlocks = [];

    let currentBlock = null;

    for (let i = 0; i < intervals.length; i++) {
      const tempId = intervals[i];
      const hour = Math.floor(i / 4);
      const minute = (i % 4) * 15;
      const timeStr = `${hour}:${minute.toString().padStart(2, "0")}`;

      if (currentBlock === null) {
        currentBlock = {
          From: timeStr,
          To: timeStr,
          TempID: tempId,
        };
      } else if (currentBlock.TempID === tempId) {
        currentBlock.To = timeStr;
      } else {
        const endHour = Math.floor((i - 1) / 4);
        const endMinute = ((i - 1) % 4) * 15 + 15;
        if (endMinute === 60) {
          currentBlock.To = `${endHour + 1}:00`;
        } else {
          currentBlock.To = `${endHour}:${endMinute.toString().padStart(2, "0")}`;
        }
        timeBlocks.push(currentBlock);

        currentBlock = {
          From: timeStr,
          To: timeStr,
          TempID: tempId,
        };
      }
    }

    if (currentBlock) {
      currentBlock.To = "24:00";
      timeBlocks.push(currentBlock);
    }

    result[dayKey] = timeBlocks;
  }

  return result;
}

// create 96-slot matrix array from time blocks
function jsonToMatrix(timeBlocks) {
  const intervals = Array(96).fill(0);

  for (const block of timeBlocks) {
    const fromParts = block.From.split(':').map(Number);
    const toParts = block.To.split(':').map(Number);
    const tempId = block.TempID;

    let startInterval = fromParts[0] * 4 + Math.floor(fromParts[1] / 15);
    let endInterval = toParts[0] * 4 + Math.ceil(toParts[1] / 15);

    if (toParts[0] === 24) {
      endInterval = 96;
    }

    startInterval = Math.max(0, startInterval);
    endInterval = Math.min(96, endInterval);
    
    for (let i = startInterval; i < endInterval; i++) {
      intervals[i] = tempId;
    }
  }

  return intervals;
}

class HeatingProfileCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
      selectedMode: { type: Number },
      isActive: { type: Boolean },
      abwesend: { type: Number },
      urlaub: { type: Number },
      temp1: { type: Number },
      temp2: { type: Number },
      temp3: { type: Number },
      temp4: { type: Number },
      matrix: { type: Array },
      showSettings: { type: Boolean },
      isFlipping: { type: Boolean },
      mqttConnected: { type: Boolean },
      isInitialized: { type: Boolean }, 
      isDrawing: { type: Boolean },
      drawStart: { type: Object },
      mqttHost: { type: String },
      mqttPort: { type: Number },
      mqttUser: { type: String },
      mqttPassword: { type: String },
      _configReady: { type: Boolean },
    };
  }

  // ANCHOR - css
  static get styles() {
    return css`
      :host {
        display: block;
        font-family: var(--paper-font-body1_-_font-family);
        box-sizing: border-box;
      }
      .card-container {
        width: 100%;
        max-width: 900px;
        margin-bottom: 0px;
        perspective: 2000px;
      }

      .flip-container {
        position: relative;
        transform-style: preserve-3d;
        transition: transform 0.6s, height 0.6s;
        box-sizing: border-box; 
      }

      .flip-container.flipped {
        transform: rotateY(180deg);
      }

      .card-side {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%; 
        overflow: hidden; 
        box-sizing: border-box;
        backface-visibility: hidden;
        -webkit-backface-visibility: hidden;
        background: var(--card-background-color, #fff);
        border-radius: 12px;
        box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,0.1));
        padding: 16px;
        border: 1px solid var(--divider-color);
      }

      .card-front {

      }

      .card-back {
        transform: rotateY(180deg);
      }

      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 24px;
      }
      .header-dots {
        display: flex;
        gap: 4px;
      }
      .dot {
        width: 12px;
        height: 12px;
        border-radius: 50%;
      }
      .dot.red { background: #ef4444; }
      .dot.yellow { background: #eab308; }
      .dot.green { background: #22c55e; }
      .title {
        font-size: 20px;
        font-weight: 600;
        color: var(--primary-text-color);
      }
      .mqtt-status {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
      }
      .status-dot.connected { background: #22c55e; }
      .status-dot.disconnected { background: #ef4444; }
      .status-text {
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      .mode-buttons {
        display: flex;
        justify-content: center;
        gap: 8px;
        flex-wrap: nowrap;
        margin-bottom: 12px;
      }
      .mode-button {
        padding: 8px 5px;
        border-radius: 8px;
        border: none;
        font-weight: 600;
        font-size: 12px;
        cursor: pointer;
        transition: all 0.2s;
        flex: 1;
      }
      .mode-button.selected {
        box-shadow: 0 0 0 2px #3b82f6;
      }
      .mode-button.bypass {
        background: #fff;
        color: #000;
        border: 1px solid #d1d5db;
      }
      .matrix-container {
        display: flex;
        justify-content: center;
      }
      .matrix-wrapper {
        display: inline-block;
      }
      .weekdays {
        display: flex;
        gap: 0;
        margin-left: 58px;
        margin-bottom: 4px;
      }
      .weekday {
        text-align: center;
        font-weight: 600;
        font-size: 12px;
        color: var(--primary-text-color);
        width: 41px;
      }
      .matrix-grid {
        user-select: none;
      }
      .matrix-row {
        display: flex;
        align-items: center;
      }
      .hour-label {
        width: 48px;
        text-align: right;
        padding-right: 8px;
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      .matrix-cells {
        display: flex;
      }
      .matrix-day {
        display: flex;
        flex-direction: column;
      }
      .matrix-cell {
        width: 40px;
        height: 8px;
        cursor: crosshair;
        transition: opacity 0.1s;
      }
      
      /* Responsive Anpassungen für kleinere Bildschirme */
      @media (max-width: 400px) {
        .weekday {
          width: 20px;
          font-size: 10px;
        }
        .matrix-cell {
          width: 20px;
          height: 4px;
        }
        .hour-label {
          width: 36px;
          font-size: 10px;
          padding-right: 4px;
        }
        .weekdays {
          margin-left: 40px;
        }
      }
      .matrix-cell:hover {
        opacity: 0.8;
      }
      .matrix-cell.first {
        border-top: 1px solid #9ca3af;
      }
      .matrix-cell.left {
        border-left: 1px solid #9ca3af;
      }
      .matrix-cell.right {
        border-right: 1px solid #9ca3af;
      }
      .matrix-cells.last {
        border-bottom: 1px solid #9ca3af;
      }
      .footer {
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        margin-top: 24px;
        gap: 16px;
      }

      .settings-button, .save-button {
        padding: 12px 0px;
        border-radius: 8px;
        border: none;
        font-weight: 600;
        font-size: 12px;
        cursor: pointer;
        transition: all 0.2s;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        height: 44px;
        box-sizing: border-box;
        flex: 1;
      }

      .settings-button {
        background: #f3f4f6;
        color: #374151;
      }

      .settings-button:hover {
        background: #e5e7eb;
      }

      .save-button {
        background: #3b82f6;
        color: white;
      }

      .save-button:hover {
        background: #2563eb;
      }

      .settings-content {
        max-width: 500px;
        margin: 0 auto;
      }
      .settings-section {
        margin-bottom: 24px;
      }
      .settings-section h3 {
        font-weight: 600;
        color: var(--primary-text-color);
        margin-bottom: 16px;
      }
      .slider-row {
        margin-bottom: 16px;
      }
      .slider-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
      }
      .slider-label {
        display: flex;
        align-items: center;
        gap: 12px;
      }
      .color-box {
        width: 24px;
        height: 24px;
        border-radius: 4px;
      }
      .slider-value {
        font-weight: 600;
        color: var(--primary-text-color);
      }
      input[type="range"] {
        width: 100%;
        height: 8px;
        border-radius: 4px;
        background: #e5e7eb;
        outline: none;
        -webkit-appearance: none;
        appearance: none;
      }
      input[type="range"]::-webkit-slider-thumb {
        -webkit-appearance: none;
        appearance: none;
        width: 20px;
        height: 20px;
        border-radius: 50%;
        background: #3b82f6;
        cursor: pointer;
      }
      input[type="range"]::-moz-range-thumb {
        width: 20px;
        height: 20px;
        border-radius: 50%;
        background: #3b82f6;
        cursor: pointer;
        border: none;
      }
      .divider {
        border-top: 1px solid #e5e7eb;
        padding-top: 16px;
      }
      .checkbox-row {
        display: flex;
        align-items: center;
        gap: 12px;
        padding-top: 16px;
      }
      input[type="checkbox"] {
        width: 20px;
        height: 20px;
        cursor: pointer;
      }
      .checkbox-label {
        font-weight: 500;
        color: var(--primary-text-color);
        cursor: pointer;
      }
    `;
  }

  constructor() {
    super();
    this.selectedMode = 0;
    this.isActive = true;
    this.abwesend = 20.0;
    this.urlaub = 5.0;
    this.temp1 = 23.0;
    this.temp2 = 20.0;
    this.temp3 = 18.0;
    this.temp4 = 5.0;
    this.showSettings = false;
    this.isFlipping = false;
    this.mqttConnected = false;
    this.isDrawing = false;
    this.drawStart = null;
    this.tempMatrix = null;
    
    this.matrix = Array(7)
      .fill()
      .map(() => Array(96).fill(0));
    
    this.mqttClient = null;
    this.ws = null;
    
    // MQTT-Zugangsdaten als Properties
    this.mqttHost = null;
    this.mqttPort = null;
    this.mqttUser = null;
    this.mqttPassword = null;
  }

  // ANCHOR - setConfig
  setConfig(config) {

    if (!config) {
      throw new Error('Konfiguration erforderlich');
    }

    const defaults = this.constructor.getStubConfig();

    this.config = {
      ...defaults,
      ...config
    };

    // Im Dialog-Kontext im Objekt speichern
    this._isDialog = config.is_dialog || false;
    this._configReady = true;

    // Wenn hass bereits verfügbar ist, versuche zu connecten
    if (this.hass) {
      this._initializeCard();
    }
  }

  // Neue Setter-Methode für hass
  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;
    
    // Nur beim ersten Setzen von hass und wenn config bereit ist
    if (!oldHass && hass && this._configReady && !this.isInitialized) {
      this._initializeCard();
    }
  }

  get hass() {
    return this._hass;
  }

  // Neue Methode: Initialisierung nur wenn BEIDE verfügbar sind
  async _initializeCard() {
    if (!this.config || !this.hass) {
      console.warn('[HeatingProfileCard] Cannot initialize - missing config or hass');
      return;
    }
    
    try {
      await this.loadPrivateConfig();
    } catch (err) {
      console.error("[HeatingProfileCard] Initialization failed:", err);
      this.isInitialized = true;
      this.requestUpdate();
    }
  }




  connectedCallback() {
    super.connectedCallback();
  }

  _handleDialogClose() {
    // console.log("Close Event");
    // Löst das Ereignis aus, das Shadow DOM-Grenzen durchdringen kann
    const event = new CustomEvent('hass-close-dialog', {
        bubbles: true,   // Wichtig: Blubbert hoch zum Dialog
        composed: true   // Wichtig: Durchdringt Shadow-DOM-Grenzen
    });
    this.dispatchEvent(event);
  }

  async loadPrivateConfig() {

    // Stellen Sie sicher, dass 'this.hass' verfügbar und authentifiziert ist.
    if (!this.hass || !this.hass.auth || !this.hass.auth.data) {
        console.error("[WebAPI] Home Assistant Auth object is not available.");
        return Promise.reject("HA Auth object missing.");
    }

    // ➡️ Neuen Token direkt aus dem HA-Objekt abrufen
    const accessToken = this.hass.auth.data.access_token;


    return new Promise((resolve, reject) => {
      try {
        // Verwende den aktuellen Host von Home Assistant
        const wsUrl = `ws://${location.host}/api/websocket`;
        //console.log("[WebAPI] Connecting to:", wsUrl);
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onmessage = async (e) => {
          const msg = JSON.parse(e.data);
          //console.log("[WebAPI] Message:", msg);
          
          if (msg.type === "auth_required") {
            //console.log("[WebAPI] Authenticating...");
            this.ws.send(JSON.stringify({ 
              type: "auth", 
              access_token: accessToken 
            }));
          } else if (msg.type === "auth_ok") {
            //console.log("[WebAPI] Auth successful, requesting config...");
            this.ws.send(JSON.stringify({ 
              id: 1, 
              type: "heatzone/get_private_config" 
            }));
          } else if (msg.id === 1 && msg.type === "result") {
            //console.log("[WebAPI] Config received:", msg.result);
            const privateConfig = msg.result;
            
            // Speichere die MQTT-Konfiguration in Properties (nicht in config)
            this.mqttHost = privateConfig.mqtt_host || privateConfig.host;
            this.mqttPort = privateConfig.mqtt_port || privateConfig.websocket_port;
            this.mqttUser = privateConfig.mqtt_user || privateConfig.username || privateConfig.user;
            this.mqttPassword = privateConfig.mqtt_password || privateConfig.password;
            
            // Topic kann in config bleiben, falls es überschrieben werden soll
            if (privateConfig.topic && !this.config.topic) {
              this.config.topic = privateConfig.topic;
            }
            
            //console.log("[WebAPI] MQTT credentials loaded");
            
            // Verbinde mit MQTT
            await this.connectMQTT();
            resolve();
          } else if (msg.id === 1 && !msg.success) {
            console.error("[WebAPI] Failed to get config:", msg.error);
            this.isInitialized = true;
            this.requestUpdate();
            reject(new Error(msg.error?.message || "Unknown error"));
          }
        };
        
        this.ws.onerror = (err) => {
          console.error("[WebAPI] WebSocket error:", err);
          this.isInitialized = true;
          this.requestUpdate();
          reject(err);
        };
        
        this.ws.onclose = () => {
          // console.log("[WebAPI] WebSocket closed");
        };
        
      } catch (err) {
        console.error("[WebAPI] Exception:", err);
        this.isInitialized = true;
        this.requestUpdate();
        reject(err);
      }
    });
  }

  async connectMQTT() {
    if (this.mqttHost && this.config && this.config.topic && this.config.profile) {
    
      if (typeof window.Paho === 'undefined') {
        try {
          //console.log("[MQTT] Attempting to load Paho from local path.");
          await this.loadScript("/local/paho-mqtt.js");
        } catch (e) {
          console.warn("[MQTT] Failed to load local Paho. Falling back to CDN.", e);
          try {
            await this.loadScript("https://cdnjs.cloudflare.com/ajax/libs/paho-mqtt/1.0.1/mqttws31.min.js");
          } catch (err) {
            console.error("[MQTT] Failed to load Paho from both local and CDN.", err);
            this.mqttConnected = false;
            this.isInitialized = true;
            this.requestUpdate();
            return;
          }
        }
        
        try {
          await this.waitForPaho();
        } catch (err) {
          console.error("[MQTT] Paho loaded but Client not available", err);
          this.mqttConnected = false;
          this.isInitialized = true;
          this.requestUpdate();
          return;
        }
      } else {
        try {
          await this.waitForPaho();
        } catch (err) {
          console.error("[MQTT] Paho exists but Client not available", err);
          this.mqttConnected = false;
          this.isInitialized = true;
          this.requestUpdate();
          return;
        }
      }
      
      this.isInitialized = true;

      try {
        // Erstelle Config-Objekt für MQTTClient aus Properties
        // Topic wird aus config.topic + "/" + config.profile zusammengesetzt
        const mqttConfig = {
          mqtt_host: this.mqttHost,
          mqtt_port: this.mqttPort,
          mqtt_user: this.mqttUser,
          mqtt_password: this.mqttPassword,
          topic: (`${this.config.topic}/${this.config.profile}`).toLowerCase(),
        };
        
        // console.log("[MQTT] Connecting with topic:", mqttConfig.topic);
        
        const client = new MQTTClient(mqttConfig, this.handleMQTTMessage.bind(this));
        await client.connect();
        this.mqttClient = client;
        this.mqttConnected = true;
        this.requestUpdate();
      } catch (err) {
        console.error("Failed to connect to MQTT:", err);
        this.mqttConnected = false;
        this.requestUpdate();
      }
    } else {
      this.isInitialized = true;
      this.requestUpdate();
    }
  }

  waitForPaho(maxAttempts = 100, interval = 50) {
    return new Promise((resolve, reject) => {
      let attempts = 0;
      
      const checkPaho = () => {
        attempts++;
        
        if (typeof window.Paho !== 'undefined' && 
            typeof window.Paho.Client === 'function') {
          //console.log("[MQTT] Paho.Client is now available after", attempts, "attempts");
          resolve();
        } else if (attempts >= maxAttempts) {
          console.error("[MQTT] Timeout after", attempts, "attempts. Paho state:", 
                      typeof window.Paho, 
                      window.Paho ? typeof window.Paho.Client : 'N/A');
          reject(new Error("Timeout waiting for Paho.Client"));
        } else {
          setTimeout(checkPaho, interval);
        }
      };
      
      checkPaho();
    });
  }
  
  loadScript(src) {
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src="${src}"]`);
      if (existing) {
        //console.log("[MQTT] Script already exists:", src);
        resolve();
        return;
      }
      
      const script = document.createElement("script");
      script.src = src;
      script.type = "text/javascript";
      
      script.onload = () => {
        //console.log("[MQTT] Script loaded successfully:", src);
        resolve();
      };
      
      script.onerror = (error) => {
        console.error("[MQTT] Failed to load script:", src, error);
        reject(new Error(`Failed to load script: ${src}`));
      };
      
      document.head.appendChild(script);
    });
  }

  handleMQTTMessage(topic, message) {
    // console.log("MQTT Message received:", topic, message);
    // profile kann mit Großbuchstaben kommen
    const fullBaseTopic =  (`${this.config.topic}/${this.config.profile}/`).toLowerCase();
    if (!topic.startsWith(fullBaseTopic)) return;

    const subtopic = topic.substring(fullBaseTopic.length);

    let value;
    try {
      value = JSON.parse(message);
    } catch {
      value = message;
    }

    const updateMatrix = (dayIndex, dayData) => {
      if (Array.isArray(dayData)) {
        const newDayMatrix = jsonToMatrix(dayData);
        const newMatrix = this.matrix.map((row, index) =>
          index === dayIndex ? newDayMatrix : row
        );
        this.matrix = newMatrix;
      }
    };
    
    switch (subtopic) {
      case "Temp1":
      case "Temp2":
      case "Temp3":
      case "Temp4":
        this[`temp${subtopic.slice(-1)}`] = parseFloat(value);
        break;

      case "TempAway":
        this.abwesend = parseFloat(value);
        break;
      
      case "TempHoliday":
        this.urlaub = parseFloat(value);
        break;

      case "Activated":
        this.isActive = (value === true || value === 'true' || value === 1);
        break;

      case "Day1": updateMatrix(0, value); break;
      case "Day2": updateMatrix(1, value); break;
      case "Day3": updateMatrix(2, value); break;
      case "Day4": updateMatrix(3, value); break;
      case "Day5": updateMatrix(4, value); break;
      case "Day6": updateMatrix(5, value); break;
      case "Day7": updateMatrix(6, value); break;
      
      default:
        console.warn(`MQTT message received for unhandled subtopic: ${subtopic}`);
        return;
    }

    this.requestUpdate();
  }

  // ANCHOR - Disconnect
  disconnectedCallback() {
    super.disconnectedCallback();

    if (this.mqttClient && this.mqttClient.connected) {
      this.mqttClient.disconnect();      
    }

    if (this.ws) {
      this.ws.close();
    }
    
  }

  getCardSize() {
    return 10;
  }

  getModeColor(modeId) {
    const isDark = this.hass && this.hass.themes && this.hass.themes.darkMode;
    const colors = {
      0: isDark ? "#1a1a1a" : "#FFFFFF",
      1: "#DC2626",
      2: "#EA580C",
      3: "#EAB308",
      4: "#16A34A",
      5: "#3B82F6",
    };
    return colors[modeId] || "#E5E7EB";
  }

  getModeLabel(modeId) {
    const labels = {
      0: "Bypass",
      1: `${this.temp1.toFixed(1)}°`,
      2: `${this.temp2.toFixed(1)}°`,
      3: `${this.temp3.toFixed(1)}°`,
      4: `${this.temp4.toFixed(1)}°`,
      5: "Aus",
    };
    return labels[modeId] || "";
  }

  handleMouseDown(day, interval) {
    this.isDrawing = true;
    this.drawStart = { day, interval };
    this.tempMatrix = this.matrix.map((row) => [...row]);

    const newMatrix = this.matrix.map((row) => [...row]);
    newMatrix[day][interval] = this.selectedMode;
    this.matrix = newMatrix;
    this.requestUpdate();
  }

  handleMouseMove(day, interval) {
    if (!this.isDrawing || !this.drawStart || !this.tempMatrix) return;

    const newMatrix = this.tempMatrix.map((row) => [...row]);
    const startDay = Math.min(this.drawStart.day, day);
    const endDay = Math.max(this.drawStart.day, day);
    const startInterval = Math.min(this.drawStart.interval, interval);
    const endInterval = Math.max(this.drawStart.interval, interval);

    for (let d = startDay; d <= endDay; d++) {
      for (let i = startInterval; i <= endInterval; i++) {
        newMatrix[d][i] = this.selectedMode;
      }
    }

    this.matrix = newMatrix;
    this.requestUpdate();
  }

  handleMouseUp() {
    this.isDrawing = false;
    this.drawStart = null;
    this.tempMatrix = null;
  }

  handleSave() {
    this.publishToMQTT();
  }

  publishToMQTT() {
    if (!this.mqttClient || !this.mqttConnected) {
      alert("MQTT nicht verbunden!");
      return;
    }

    const data = matrixToJSON(
      this.matrix,
      [this.temp1, this.temp2, this.temp3, this.temp4],
      this.abwesend,
      this.urlaub,
      this.isActive
    );

    this.mqttClient.publish("Temp1", data.Temp1);
    this.mqttClient.publish("Temp2", data.Temp2);
    this.mqttClient.publish("Temp3", data.Temp3);
    this.mqttClient.publish("Temp4", data.Temp4);
    this.mqttClient.publish("TempAway", data.TempAway);
    this.mqttClient.publish("TempHoliday", data.TempHoliday);
    this.mqttClient.publish("Activated", data.Activated);
    
    for (let i = 1; i <= 7; i++) {
      this.mqttClient.publish(`Day${i}`, data[`Day${i}`]);
    }

    console.log("Published to MQTT:", data);
  }

  // ANCHOR - setFlipContainerHeight
  setFlipContainerHeight() {
    const flipContainer = this.shadowRoot.querySelector('.flip-container');
    const cardFront = this.shadowRoot.querySelector('.card-front');
    const cardBack = this.shadowRoot.querySelector('.card-back');
    
    if (!flipContainer) return;
    
    let targetHeight = this.showSettings ? BACK_CARD_HEIGHT : FRONT_CARD_HEIGHT;
  
    let offset = 0;
    if (this._isDialog) {
      if (this.showSettings) offset = 24;
      else offset = 12; 
    }

    flipContainer.style.height = `${targetHeight - offset}px`;

    // 👇 Setze die NICHT-SICHTBARE Seite auf height: 0
    if (this.showSettings) {
      // Back ist sichtbar
      if (cardBack) cardBack.style.height = `${BACK_CARD_HEIGHT - offset}px`;
      if (cardFront) cardFront.style.height = '0'; // 👈 Front verstecken
    } else {
      // Front ist sichtbar
      if (cardFront) cardFront.style.height = `${FRONT_CARD_HEIGHT - offset}px`;
      if (cardBack) cardBack.style.height = '0'; // 👈 Back verstecken
    }
    
    // Event feuern
    if (this._isDialog) {
      this.dispatchEvent(new CustomEvent('card-size-changed', {
        bubbles: true,
        composed: true,
        detail: { height: targetHeight }
      }));
    }
    
    window.dispatchEvent(new Event('resize'));
  }

  toggleView() {
    this.isFlipping = true;

    this.requestUpdate();

    this.showSettings = !this.showSettings;
   
    this.setFlipContainerHeight();  

    setTimeout(() => {
      this.isFlipping = false;
      this.requestUpdate();
    }, 600);
  }

  firstUpdated(changedProperties) {
    super.firstUpdated(changedProperties);
    this.setFlipContainerHeight();
  }

  // ANCHOR - html
  render() {

    const t = (key) => this._hass.localize(key);

    const labelSave      = t("ui.common.save");   // "Speichern"
    const labelBack      = t("ui.common.back");   // "Zurück"
    const labelSettings  = t("panel.config");     // "Einstellungen"

    const labelAway      = t("state_badge.person.not_home"); // "Abwesend"
    const labelHoliday   = t("ui.card.alarm_control_panel.modes.armed_vacation"); // "Urlaub"


    // Wenn config fehlt - zeige Fehler
    if (!this.config) {
      return html`
        <ha-card style="padding: 16px;">
          <div style="text-align: center; color: var(--error-color);">
            ⚠️ Keine Konfiguration gefunden
          </div>
        </ha-card>
      `;
    }


    if (!this.isInitialized) {
      return html`
        <ha-card style="padding: 16px;">
          <div style="text-align: center; color: var(--secondary-text-color);">
            Heizungsprofil wird geladen...
            <ha-circular-progress active size="small"></ha-circular-progress>
          </div>
        </ha-card>
      `;
    }

    const weekDays = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];

    return html`
      <div class="card-container">
        <div class="flip-container ${this.showSettings ? "flipped" : ""}" style="height: ${FRONT_CARD_HEIGHT}px">
          <!-- Front Side - Matrix -->
          <div class="card-side card-front">
            <div class="header">
              <div id="close_id" class="header-dots" @click="${this._handleDialogClose}">
                <div class="dot red"></div>
                <div class="dot yellow"></div>
                <div class="dot green"></div>
              </div>
              <div class="title">${this.config.title}</div>
              <div class="mqtt-status">
                <div
                  class="status-dot ${this.mqttConnected
                    ? "connected"
                    : "disconnected"}"
                ></div>
                <span class="status-text"
                  >${this.mqttConnected ? "MQTT" : "Offline"}</span
                >
              </div>
            </div>

            <div class="mode-buttons">
              ${[0, 1, 2, 3, 4, 5].map(
                (mode) => {
                  const isDark = this.hass && this.hass.themes && this.hass.themes.darkMode;
                  const backgroundColor = mode !== 0 ? this.getModeColor(mode) : (isDark ? "#1a1a1a" : "#FFFFFF");
                  const textColor = mode === 0 
                    ? (isDark ? "#FFFFFF" : "#000000")
                    : (mode === 4 ? "#000" : "#fff");
                  const borderColor = isDark ? "#444444" : "#d1d5db";
                  
                  return html`
                    <button
                      class="mode-button ${mode === 0 ? "bypass" : ""} ${this
                        .selectedMode === mode
                        ? "selected"
                        : ""}"
                      style="background-color: ${backgroundColor}; color: ${textColor}; ${mode === 0 ? `border: 1px solid ${borderColor};` : ''}"
                      @click=${() => {
                        this.selectedMode = mode;
                        this.requestUpdate();
                      }}
                    >
                      ${this.getModeLabel(mode)}
                    </button>
                  `;
                }
              )}
            </div>

            <div class="matrix-container">
              <div class="matrix-wrapper">
                <div class="weekdays">
                  ${weekDays.map((day) => html`<div class="weekday">${day}</div>`)}
                </div>

                <div
                  class="matrix-grid"
                  @mouseup=${this.handleMouseUp}
                  @mouseleave=${this.handleMouseUp}
                >
                  ${Array.from({ length: 24 }, (_, hour) => html`
                    <div class="matrix-row">
                      <div class="hour-label">${hour}:00</div>
                      <div class="matrix-cells ${hour === 23 ? "last" : ""}">
                        ${weekDays.map(
                          (_, dayIdx) => html`
                            <div class="matrix-day">
                              ${Array.from({ length: 4 }, (_, intervalIdx) => {
                                const totalInterval = hour * 4 + intervalIdx;
                                const modeId = this.matrix[dayIdx][totalInterval];
                                return html`
                                  <div
                                    class="matrix-cell ${intervalIdx === 0
                                      ? "first"
                                      : ""} ${dayIdx === 0 ? "left" : ""} right"
                                    style="background-color: ${this.getModeColor(
                                      modeId
                                    )};"
                                    @mousedown=${() =>
                                      this.handleMouseDown(dayIdx, totalInterval)}
                                    @mouseenter=${() =>
                                      this.handleMouseMove(dayIdx, totalInterval)}
                                  ></div>
                                `;
                              })}
                            </div>
                          `
                        )}
                      </div>
                    </div>
                  `)}
                </div>
              </div>
            </div>

            <div class="footer">
              <button class="settings-button" @click=${this.toggleView}>
                <span>${labelSettings}</span>
              </button>

              <button class="save-button" @click=${this.handleSave}>
                ${labelSave}
              </button>
            </div>
          </div>

          <!-- Back Side - Settings -->
          <div class="card-side card-back">
            <div class="header">
              <div class="header-dots" @click="${this._handleDialogClose}">
                <div class="dot red"></div>
                <div class="dot yellow"></div>
                <div class="dot green"></div>
              </div>
              <div class="title">${labelSettings}</div>
              <div style="width: 20px;"></div>
            </div>

            <div class="settings-content">
              <div class="settings-section">
                <h3>Temp-Settings</h3>

                <div class="slider-row">
                  <div class="slider-header">
                    <div class="slider-label">
                      <div
                        class="color-box"
                        style="background-color: #DC2626;"
                      ></div>
                      <span>Temp 1:</span>
                    </div>
                    <span class="slider-value">${this.temp1.toFixed(1)}°C</span>
                  </div>
                  <input
                    type="range"
                    min="15"
                    max="30"
                    step="0.5"
                    .value=${this.temp1}
                    @input=${(e) => {
                      this.temp1 = parseFloat(e.target.value);
                      this.requestUpdate();
                    }}
                  />
                </div>

                <div class="slider-row">
                  <div class="slider-header">
                    <div class="slider-label">
                      <div
                        class="color-box"
                        style="background-color: #EA580C;"
                      ></div>
                      <span>Temp 2:</span>
                    </div>
                    <span class="slider-value">${this.temp2.toFixed(1)}°C</span>
                  </div>
                  <input
                    type="range"
                    min="15"
                    max="30"
                    step="0.5"
                    .value=${this.temp2}
                    @input=${(e) => {
                      this.temp2 = parseFloat(e.target.value);
                      this.requestUpdate();
                    }}
                  />
                </div>

                <div class="slider-row">
                  <div class="slider-header">
                    <div class="slider-label">
                      <div
                        class="color-box"
                        style="background-color: #EAB308;"
                      ></div>
                      <span>Temp 3:</span>
                    </div>
                    <span class="slider-value">${this.temp3.toFixed(1)}°C</span>
                  </div>
                  <input
                    type="range"
                    min="15"
                    max="30"
                    step="0.5"
                    .value=${this.temp3}
                    @input=${(e) => {
                      this.temp3 = parseFloat(e.target.value);
                      this.requestUpdate();
                    }}
                  />
                </div>

                <div class="slider-row">
                  <div class="slider-header">
                    <div class="slider-label">
                      <div
                        class="color-box"
                        style="background-color: #16A34A;"
                      ></div>
                      <span>Temp 4:</span>
                    </div>
                    <span class="slider-value">${this.temp4.toFixed(1)}°C</span>
                  </div>
                  <input
                    type="range"
                    min="5"
                    max="20"
                    step="0.5"
                    .value=${this.temp4}
                    @input=${(e) => {
                      this.temp4 = parseFloat(e.target.value);
                      this.requestUpdate();
                    }}
                  />
                </div>
              </div>

              <div class="settings-section divider">
                <div class="slider-row">
                  <div class="slider-header">
                    <div class="slider-label">
                      <span>${labelAway}:</span>
                    </div>
                    <span class="slider-value">${this.abwesend.toFixed(1)}°C</span>
                  </div>
                  <input
                    type="range"
                    min="5"
                    max="25"
                    step="0.5"
                    .value=${this.abwesend}
                    @input=${(e) => {
                      this.abwesend = parseFloat(e.target.value);
                      this.requestUpdate();
                    }}
                  />
                </div>

                <div class="slider-row">
                  <div class="slider-header">
                    <div class="slider-label">
                      <span>${labelHoliday}:</span>
                    </div>
                    <span class="slider-value">${this.urlaub.toFixed(1)}°C</span>
                  </div>
                  <input
                    type="range"
                    min="5"
                    max="20"
                    step="0.5"
                    .value=${this.urlaub}
                    @input=${(e) => {
                      this.urlaub = parseFloat(e.target.value);
                      this.requestUpdate();
                    }}
                  />
                </div>
              </div>

              <div class="checkbox-row">
                <input
                  type="checkbox"
                  id="active"
                  .checked=${this.isActive}
                  @change=${(e) => {
                    this.isActive = e.target.checked;
                    this.requestUpdate();
                  }}
                />
                <label class="checkbox-label" for="active">Profil aktiv</label>
              </div>
            </div>

            <div class="footer">
              <button class="settings-button" @click=${this.toggleView}>
                <span>${labelBack}</span>
              </button>

              <button class="save-button" @click=${this.handleSave}>
                ${labelSave}
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  static getStubConfig() {
    return {
      title: "Heizungsprofil",
      topic: "heatzone/profiles",
      profile: "default",
    };
  }

  static getConfigForm() {
    return {
      schema: [
        {
          name: "title", 
          label: "Titel",
          selector: { text: {} },
        },
        {
          name: "topic", 
          label: "MQTT Topic", 
          helper: "Das Basis-Topic für die Heizungssteuerung",
          selector: { text: {} },
        },
        {
          name: "profile", 
          label: "Profile Name",
          helper: "Der Name des Profils (wird an das Topic angehängt)",
          selector: { text: {} },
        },
      ],
    };
  }
}

customElements.define("heatzone-profile-card", HeatingProfileCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "heatzone-profile-card",
  name: "Heatzone Profile Card",
  description: "A card to manage heating profiles with MQTT integration",
  preview: false,
});

console.info(
  "%c HEATZONE-PROFILE-CARD %c 0.9.0 ",
  "color: white; background: coral; font-weight: 700;",
  "color: coral; background: white; font-weight: 700;"
);