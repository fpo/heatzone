class HeatzoneCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = {};
    this._hass = null;
  }

  // ANCHOR - setConfig
  static getStubConfig() {
    return { 
      entity: '',
      name: '',
      color: '#e0e0e0',
      design: 'design1',
      
      // Boolean Flags mit korrekten Defaults
      backcolor_system: true,
      textcolor_system: true,
      ac_trans: false,
      
      // Farben
      backcolor_light: '#ffffff',
      backcolor_dark: '#000000',
      textcolor_light: '#000000',
      textcolor_dark: '#ffffff',
      
      // Größen
      temp_size: 2.5,
      title_size: 1.0,
      info_size: 0.875,
      padding: 0
    };
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error('Bitte ein Gerät auswählen (entity erforderlich)');
    }
    
    // ✅ getStubConfig als Basis, dann config drüber mergen
    const defaults = this.constructor.getStubConfig();
    this._config = {
      ...defaults,
      ...config
    };
    
    this.render();
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;
    
    if (!oldHass || !this._config.entity) {
      this.render();
      return;
    }

    const deviceName = this._config.entity;
    const entities = [
      `sensor.${deviceName}_temperature_sensor`,
      `sensor.${deviceName}_target_temperature`,
      `sensor.${deviceName}_humidity_sensor`,
      `switch.${deviceName}_boost`,
      `select.${deviceName}_mode`,
      `number.${deviceName}_manual_temp`,
      `binary_sensor.${deviceName}_window_sensor`
    ];
    
    const changed = entities.some(entity => {
      const oldState = oldHass.states[entity];
      const newState = hass.states[entity];
      return !oldState || !newState || oldState.state !== newState.state;
    });
    
    if (changed) {
      this.render();
    }
  }

  static getConfigElement() {
    return document.createElement('heatzone-card-editor');
  }

  getCardSize() {
    let size = 3; // Base size
    
    // Check if manual mode is active
    if (this._hass && this._config.entity) {
      const modeSelect = this._hass.states[`select.${this._config.entity}_mode`];
      if (modeSelect && modeSelect.state === 'Manuell') {
        size += 1; // Manual slider
      }
    }
    
    return size;
  }

  
  _openProfileDialog(ev) {
      if (ev) ev.stopPropagation();
      
      const deviceName = this._config.entity;
      const profileEntityId = `text.${deviceName}_profile`;
      const profileState = this._hass.states[profileEntityId];
      
      let profile = 'UNKNOWN_PROFILE';
      if (profileState) {
          profile = profileState.state; 
      } else {
          console.warn(`[HeatzoneCard] Topic-Entität ${profileEntityId} nicht gefunden.`);
      }
      
      const cardConfig = {
          type: 'heatzone-profile-card', 
          profile: `${profile}`, 
          title: `${profile}`,
          is_dialog: true,
      };
      
      // ✅ KORREKT: show-dialog Event für Custom Cards
      const dialogEvent = new CustomEvent('show-dialog', {
          bubbles: true,
          composed: true,
          detail: {
              dialogTag: 'heatzone-profile-dialog',
              dialogImport: null,
              dialogParams: {
                  card: cardConfig,
                  hass: this._hass,
              }
          }
      });
      
      // Erstelle das Dialog-Element
      this._createDialog(cardConfig);
      
      this.dispatchEvent(dialogEvent);
  }

  // ANCHOR - createDialog
  _createDialog(cardConfig) {
    let dialog = document.querySelector('ha-dialog');
    if (dialog) {
      dialog.remove();
    }

    dialog = document.createElement('ha-dialog');
    
    dialog.addEventListener('hass-close-dialog', () => {
      dialog.close();
    });

    dialog.setAttribute('scrimClickAction', 'close');
    dialog.setAttribute('escapeKeyAction', 'close');
    dialog.style.setProperty('--mdc-dialog-max-width', '90vw');
    dialog.style.setProperty('--mdc-dialog-min-width', '400px');
    dialog.style.setProperty('--ha-dialog-border-radius', '12px');
    
    dialog.hideActions = true; 

    const card = document.createElement(cardConfig.type);
    
    const dialogCardConfig = {
      ...cardConfig,
      is_dialog: true 
    };
    
    card.setConfig(dialogCardConfig);
    card.hass = this._hass;
    
    dialog.appendChild(card);
    
    // 👇 Event Handler
    card.addEventListener('card-size-changed', (e) => {
      console.log('📏 Card-Höhe geändert:', e.detail.height);
    });

    document.body.appendChild(dialog);
    dialog.open = true;
    
    // Initial Setup - Wichtig für padding
    setTimeout(() => {
      const shadowRoot = dialog.shadowRoot;
      if (shadowRoot) {
        const content = shadowRoot.querySelector('.mdc-dialog__content');
        if (content) {
          //content.style.overflowY = 'auto';
          content.style.padding = '0';
        }
      }
    }, 50);

    dialog.addEventListener('closed', () => {
      dialog.remove();
    });

    
  }

  


  getBackgroundColor(isDark) {
    if (this._config.backcolor_system === true) 
      // return 'var(--ha-card-background)';
      return 'var(--card-background-color)';
    else {
      if (isDark) {
        return this._config.backcolor_dark || '#1d1d1d';
      } else {
        return this._config.backcolor_light || '#ffffff';
      }
    }
  }

  getTextColor(isDark) {
    if (this._config.textcolor_system === true) 
      return this.getResolvedTextColor();
    else {
      if (isDark) {
        return this._config.textcolor_dark || '#ffffff';
      } else {
        return this._config.textcolor_light || '#000000';
      }
    }
  }

  // Farbwert holen für --primary-text-color
  getResolvedTextColor() {
      // Hole die berechneten Stile vom HTML-Wurzelelement
      const style = window.getComputedStyle(document.documentElement);
      
      // Rufe den Wert von --primary-text-color ab
      const variableValue = style.getPropertyValue('--primary-text-color').trim();
      
      // Fallback, falls die Variable nicht gefunden wird
      return variableValue || '#000000'; 
  }

  getAccentTextColor = (bgColor) => {
    const hex = bgColor.replace('#', '');
    const r = parseInt(hex.substr(0, 2), 16);
    const g = parseInt(hex.substr(2, 2), 16);
    const b = parseInt(hex.substr(4, 2), 16);
    const brightness = (r * 299 + g * 587 + b * 114) / 1000;
    if (this._config.ac_trans === true) {
      return this.getResolvedTextColor();
    } else {
      return brightness > 155 ? '#000000' : '#ffffff';
    }
  }

  getLocalizedMode(mode) {
    const localized = this._hass.localize(
      `component.heatzone.entity.select.mode.state.${mode}`
    );
    return localized || mode;
  }



  render() {
    if (!this._hass || !this._config.entity) return;

    const deviceName = this._config.entity;
    const accentColor = this._config.color || '#e0e0e0';    
    const isDark = this._hass.themes.darkMode;
    const backgroundColor = this.getBackgroundColor(isDark);
    const textColor = this.getTextColor(isDark);
    const tempSize = this._config.temp_size || 2.5;
    const titleSize = this._config.title_size || 1.0;
    const infoSize = this._config.info_size || 0.875;
    const design = this._config.design || 'design1';
    const padding = this._config.padding || 0;
    const accentTextColor = this.getAccentTextColor(accentColor);
    const ac_trans = this._config.ac_trans || false;    

    const currentTemp = this._hass.states[`sensor.${deviceName}_temperature_sensor`];
    const targetTemp = this._hass.states[`sensor.${deviceName}_target_temperature`];
    const humidity = this._hass.states[`sensor.${deviceName}_humidity_sensor`];
    const boostSwitch = this._hass.states[`switch.${deviceName}_boost`];
    const modeSelect = this._hass.states[`select.${deviceName}_mode`];
    const manualTemp = this._hass.states[`number.${deviceName}_manual_temp`];

    const temp = currentTemp ? parseFloat(currentTemp.state) : 0;
    const target = targetTemp ? parseFloat(targetTemp.state) : 0;
    const hum = humidity ? parseInt(humidity.state) : 0;
    const isBoost = boostSwitch ? boostSwitch.state === 'on' : false;
    const mode = modeSelect ? modeSelect.state : 'Profil';
    const manualTempValue = manualTemp ? parseFloat(manualTemp.state) : 20;
    const modeOptions = modeSelect && modeSelect.attributes.options ? modeSelect.attributes.options : ['Profil', 'Manuell', 'Aus'];

    const displayName = this._config.name || deviceName.replace(/_/g, ' ');

    const windowSensor = this._hass.states[`binary_sensor.${deviceName}_window_sensor`];
    const isWindowOpen = windowSensor ? windowSensor.state === 'on' : false;

    // ANCHOR - css
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
        }
        ha-card {
          padding: ${design === 'design2' ? '0' : '8px'};
          border-radius: 12px;
          transition: all 0.3s ease;
          overflow: visible;
          background: ${backgroundColor};
          color: ${textColor};
        }
        ha-card.boost-active {
          background: ${isDark ? "#3b2408" : "#fff3e0"};
          border: 2px solid #ff8c00;
          animation: pulseGlow 1.8s ease-in-out infinite;
        }
        @keyframes pulseGlow {
          0%, 100% { box-shadow: 0 0 12px rgba(255, 140, 0, 0.5); }
          50% { box-shadow: 0 0 28px rgba(255, 140, 0, 1); }
        }
        .header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
          padding: 4px 12px;
          ${ac_trans !== true
            ? (design === 'design2'
                ? `background: ${accentColor}; border: none; border-radius: 10px 10px 0 0;`
                : `background: ${accentColor}; border: 1px solid ${accentColor}; border-radius: 12px;`
              )
            : ''}
          transition: background 0.3s;
        }
        .header h2 {
          margin: 0;
          font-size: ${titleSize}rem;
          font-weight: 500;
          text-transform: capitalize;
          color: ${accentTextColor};
        }

        .window-icon {
          color: ${accentTextColor};
          font-size: 1.2rem;
          animation: windowPulse 2s ease-in-out infinite;
        }
        @keyframes windowPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.6; }
        }

        .settings-icon {
          cursor: pointer;
          color: ${accentTextColor};
          transition: transform 0.2s;
        }
        .settings-icon:hover {
          transform: scale(1.1);
        }
        .main-content {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
          ${design === 'design2' 
            ? `padding: ${padding}px 12px;` 
            : `padding: ${padding}px 0px;`}
        }
        .temperature {
          font-size: ${tempSize}rem;
          font-weight: 500;
          display: flex;
          align-items: flex-start;
          line-height: 1;
        }
        .temp-unit {
          font-size: ${tempSize / 2}rem;
          margin-left: 4px;
          opacity: 0.7;
          margin-top: 4px;
        }
        .info {
          text-align: left;
          font-size: ${infoSize}rem;
        }
        .humidity {
          color: #2196f3;
          margin-bottom: 4px;
          display: flex;
          align-items: flex-start;
          gap: 4px;
          line-height: 1;
        }
        .humidity-temp {
          display: flex;
          align-items: flex-start;
        }
        .humidity-unit {
          font-size: ${infoSize / 2}rem;
          margin-left: 1px;
          opacity: 0.7;
        }
        .target {
          color: #ff8c00;
          display: flex;
          align-items: flex-start;
          gap: 4px;
          line-height: 1;
        }
        .target-temp {
          display: flex;
          align-items: flex-start;
        }
        .target-unit {
          font-size: ${infoSize / 2}rem;
          margin-left: 1px;
          opacity: 0.7;
        }
        .manual-slider {
          margin-bottom: 12px;
          ${design === 'design2' ? 'padding: 0 12px;' : ''}
        }
        .manual-slider label {
          display: block;
          font-size: 14px;
          color: var(--secondary-text-color);
          margin-bottom: 8px;
        }
        .manual-slider input[type="range"] {
          width: 100%;
          margin: 8px 0;
        }
        .manual-slider .value {
          font-size: 14px;
          margin-top: 4px;
        }
        .controls {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
          ${design === 'design2' ? 'padding: 0 8px 8px 8px;' : ''}
        }
        .boost-button {
          height: 40px;
          min-height: 40px;
          width: 100%;
          border: none;
          border-radius: 12px;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          padding: 0 12px;
          line-height: normal;
        }
        .boost-button.inactive {
          background: ${isDark ? "#FF6F35" : "#ffe0b2"};
          color: ${isDark ? "#ffffffff" : "#e65100"};
          border: 1px solid ${isDark ? "#FF6F35" : "#ffb74d"};
        }
        .boost-button.active {
          background: ${isDark ? "#e87807ff" : "#ff8c00"};
          color: white;
          animation: pulseGlow 1.8s ease-in-out infinite;
        }
        .boost-button:hover {
          box-shadow: ${isDark ? "0 0 0px 3px #ff8c00" : "0 0 8px 3px #ffcc80"}; 
        }
        .mode-select {
          color: ${textColor};
          font: inherit;
          height: 40px;
          min-height: 40px;
          width: 100%;
          border: 1px solid #ccc;
          border: 1px solid var(--divider-color);
          border-radius: 12px;
          font-size: 14px;
          background: #e0e0e0;
          background-color: var(--input-fill-color);
          cursor: pointer;
          font-weight: 500;
          text-align: center;
          text-align-last: center;
          -webkit-appearance: none;
          -moz-appearance: none;
          appearance: none;
          background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='${encodeURIComponent(textColor)}' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3e%3cpolyline points='6 9 12 15 18 9'%3e%3c/polyline%3e%3c/svg%3e");
          background-repeat: no-repeat;
          background-position: right 8px center;
          background-size: 16px;
          line-height: normal;
          padding: 8px 20px 8px 8px;
        }
        .mode-select option {
          text-align: center;
          text-indent: 0;
          font-family: inherit;
          font-size: inherit;
          font-weight: inherit;
        }
        select option, select optgroup { font-family: inherit; font-size: inherit; font-weight: inherit; }
        select * { font-family: inherit; font-size: inherit; font-weight: inherit; }
      </style>
      <!-- ANCHOR - html -->
      <ha-card class="${isBoost ? 'boost-active' : ''}">
        <div class="header">
          ${isWindowOpen ? `<span class="window-icon">❄️</span>` : ''}
          <h2>${displayName}</h2>
          <span class="settings-icon" id="settings-icon">⚙️</span>
        </div>
        <div class="main-content">
          <div class="temperature">
            <span>${temp.toFixed(1)}</span>
            <span class="temp-unit">°C</span>
          </div>
          <div class="info">
            <div class="humidity">
              <span>💧</span>
              <div class="humidity-temp">
                <span>${hum}</span>
                <span class="humidity-unit">%</span>
              </div>
            </div>
            <div class="target">
              <span>🌡️</span>
              <div class="target-temp">
                <span>${target.toFixed(1)}</span>
                <span class="target-unit">°C</span>
              </div>
            </div>
          </div>
        </div>
        ${mode === 'manual' ? `
          <div class="manual-slider">
            <label>Zieltemperatur</label>
            <input 
              type="range" 
              min="5" 
              max="30" 
              step="0.5" 
              value="${manualTempValue}"
              id="temp-slider"
            />
            <div class="value">${manualTempValue.toFixed(1)} °C</div>
          </div>
        ` : ''}
        <div class="controls">
          <button class="boost-button ${isBoost ? 'active' : 'inactive'}" id="boost-btn">
            ${isBoost ? 'Boost' : 'Boost'}
          </button>
          <select class="mode-select" id="mode-select">
            ${modeOptions.map(option => `
              <option value="${option}" ${mode === option ? 'selected' : ''}>
                ${this.getLocalizedMode(option)}
              </option>
            `).join('')}
          </select>
        </div>
      </ha-card>
    `;

    // Settings icon - öffnet Dialog
    const settingsIcon = this.shadowRoot.getElementById('settings-icon');
    if (settingsIcon) {
      settingsIcon.onclick = (e) => this._openProfileDialog(e);
    }

    // Boost button
    const boostBtn = this.shadowRoot.getElementById('boost-btn');
    if (boostBtn) {
      boostBtn.onclick = () => this.toggleBoost();
    }

    // Mode select
    const modeSelectEl = this.shadowRoot.getElementById('mode-select');
    if (modeSelectEl) {
      const newModeSelect = modeSelectEl.cloneNode(true);
      modeSelectEl.parentNode.replaceChild(newModeSelect, modeSelectEl);
      
      newModeSelect.addEventListener('change', (e) => {
        e.preventDefault();
        e.stopPropagation();
        this.changeMode(e.target.value);
      });
    }

    // Temperature slider
    const tempSlider = this.shadowRoot.getElementById('temp-slider');
    if (tempSlider) {
      const newSlider = tempSlider.cloneNode(true);
      tempSlider.parentNode.replaceChild(newSlider, tempSlider);
      
      let timeout;
      newSlider.addEventListener('input', (e) => {
        const value = e.target.value;
        const valueDisplay = this.shadowRoot.querySelector('.manual-slider .value');
        if (valueDisplay) {
          valueDisplay.textContent = `${parseFloat(value).toFixed(1)} °C`;
        }
        clearTimeout(timeout);
        timeout = setTimeout(() => {
          this.updateManualTemp(value);
        }, 500);
      });
    }
  }

  toggleBoost() {
    const deviceName = this._config.entity;
    const service = this._hass.states[`switch.${deviceName}_boost`].state === 'on' 
      ? 'switch.turn_off' 
      : 'switch.turn_on';
    
    this._hass.callService('switch', service.split('.')[1], {
      entity_id: `switch.${deviceName}_boost`
    });
  }

  changeMode(newMode) {
    const deviceName = this._config.entity;
    this._hass.callService('select', 'select_option', {
      entity_id: `select.${deviceName}_mode`,
      option: newMode
    });
  }

  updateManualTemp(value) {
    const deviceName = this._config.entity;
    const numValue = parseFloat(value);
    if (isNaN(numValue)) {
      return;
    }
    this._hass.callService('number', 'set_value', {
      entity_id: `number.${deviceName}_manual_temp`,
      value: numValue
    });
  }

  requestUpdate() {
    setTimeout(() => this.render(), 0);
  }
}

// ANCHOR - Editor für die GUI-Konfiguration mit ha-form
class HeatzoneCardEditor extends HTMLElement {
  constructor() {
    super();
    this._config = {};
    this._hass = null;
    this._rendered = false;
  }

  setConfig(config) {
    this._config = config || {};

    // ✨ rows:'auto' sicherstellen (ohne Mutation) Funktioniert nur bei value Änderung
    // Nicht bei Layoutänderung durch Anwender. Keinen anderen Weg gefunden das zu erzwingen.
    const go = (this._config.grid_options && typeof this._config.grid_options === 'object')
      ? this._config.grid_options
      : {};
    if (go.rows !== 'auto') {
      console.log("Nicht auto"); 
      this._config = { ...this._config, grid_options: { ...go, rows: 'auto' } };
      console.log("Danach");
    }

    //console.info('[HeatzoneCard] Aktuelle Konfiguration nach setConfig:', this._config);
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._rendered) {
      this.render();
    }
  }

  _hexToRgb(hex) {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    const rgb = result ? {
      r: parseInt(result[1], 16),
      g: parseInt(result[2], 16),
      b: parseInt(result[3], 16)
    } : { r: 224, g: 224, b: 224 };
    return rgb;
  }

  _rgbToHex(r, g, b) {
    return '#' + [r, g, b].map(x => {
      const hex = x.toString(16);
      return hex.length === 1 ? '0' + hex : hex;
    }).join('');
  }

  _getFormData() {
    const hex = this._config.color || '#e0e0e0';
    const rgb = this._hexToRgb(hex);

    // 🟢 Sicherstellen, dass backcolor_light existiert
    const back_hex = this._config.backcolor_light || '#ffffff';
    const back_rgb = this._hexToRgb(back_hex);

    // 🟢 Sicherstellen, dass backcolor_dark existiert
    const back_hex_dark = this._config.backcolor_dark || '#000000';
    const back_rgb_dark = this._hexToRgb(back_hex_dark);

    // 🟢 Sicherstellen, dass textcolor_light existiert
    const text_hex_light = this._config.textcolor_light || '#000000';
    const text_rgb_light = this._hexToRgb(text_hex_light);

    // 🟢 Sicherstellen, dass textcolor_dark existiert
    const text_hex_dark = this._config.textcolor_dark || '#ffffff';
    const text_rgb_dark = this._hexToRgb(text_hex_dark);


    // 🟢 Fallback falls Konfiguration leer oder fehlerhaft
    if (!back_rgb || isNaN(back_rgb.r) || isNaN(back_rgb.g) || isNaN(back_rgb.b)) {
      console.warn('HeatzoneCard: backcolor_light nicht definiert – Fallback #ffffff verwendet');
      back_rgb = { r: 255, g: 255, b: 255 };
    }

    // 🟢 Fallback falls Konfiguration leer oder fehlerhaft
    if (!back_rgb_dark || isNaN(back_rgb_dark.r) || isNaN(back_rgb_dark.g) || isNaN(back_rgb_dark.b)) {
      console.warn('HeatzoneCard: backcolor_dark nicht definiert – Fallback #ffffff verwendet');
      back_rgb_dark = { r: 255, g: 255, b: 255 };
    }

    // 🟢 Fallback falls Konfiguration leer oder fehlerhaft
    if (!text_rgb_light || isNaN(text_rgb_light.r) || isNaN(text_rgb_light.g) || isNaN(text_rgb_light.b)) {
      console.warn('HeatzoneCard: textcolor_light nicht definiert – Fallback #000000 verwendet');
      text_rgb_light = { r: 0, g: 0, b: 0 };
    }

    // 🟢 Fallback falls Konfiguration leer oder fehlerhaft
    if (!text_rgb_dark || isNaN(text_rgb_dark.r) || isNaN(text_rgb_dark.g) || isNaN(text_rgb_dark.b)) {
      console.warn('HeatzoneCard: backcolor_dark nicht definiert – Fallback #ffffff verwendet');
      text_rgb_dark = { r: 255, g: 255, b: 255 };
    }

    // console.log("backcolor_system:" + this._config.backcolor_system)

    return {
      entity: this._config.entity || '',
      name: this._config.name || '',
      design: this._config.design || 'design1',
      color: [rgb.r, rgb.g, rgb.b],
      ac_trans: this._config.ac_trans,
      backcolor_system: this._config.backcolor_system,
      textcolor_system: this._config.textcolor_system,
      backcolor_light: [back_rgb.r, back_rgb.g, back_rgb.b],
      backcolor_dark: [back_rgb_dark.r, back_rgb_dark.g, back_rgb_dark.b],
      textcolor_light: [text_rgb_light.r, text_rgb_light.g, text_rgb_light.b],
      textcolor_dark: [text_rgb_dark.r, text_rgb_dark.g, text_rgb_dark.b],
      padding: this._config.padding || 0,
      temp_size: this._config.temp_size || 2.5,
      title_size: this._config.title_size || 24,
      info_size: this._config.info_size || 18
    };
  }

  _getSchema() {
    if (!this._hass) return [];

    const devices = Object.keys(this._hass.states)
      .filter(entity => entity.startsWith('number.') && entity.endsWith('_manual_temp'))
      .map(entity => entity.replace('number.', '').replace('_manual_temp', ''));

    const deviceOptions = devices.map(device => ({
      value: device,
      label: device.replace(/_/g, ' ')
    }));

    return [
      {
        name: 'entity',required: true,
        selector: { select: { options: deviceOptions,mode: 'dropdown' } }
      },
      { 
        name: 'name', 
        selector: { text: {} } 
      },
      {
        name: 'design',
        selector: { select: 
          { options: [
              { value: 'design1', label: 'Design 1 (Karte mit Rahmen)' },
              { value: 'design2', label: 'Design 2 (Balken-Header)' }
            ],
            mode: 'dropdown'
          }
        }
      },
      {
          type: "grid",
          name: "",
          schema: [
            { name: 'color', selector: { color_rgb: {} } },
            { name: "ac_trans", default: false, selector: { boolean: {} }, },
            { name: "backcolor_system", default: true, selector: { boolean: {} }, },
            { name: "textcolor_system", default: true, selector: { boolean: {} }, },
            { name: 'backcolor_light', selector: { color_rgb: {} } },
            { name: 'textcolor_light', selector: { color_rgb: {} } },
            { name: 'backcolor_dark', selector: { color_rgb: {} } },
            { name: 'textcolor_dark', selector: { color_rgb: {} } },
          ],
      },
      {
        name: 'padding', default: 10,
        selector: { number: { min: 0, max: 30, step: 1, mode: 'slider' } }
      },
      {
        name: 'title_size', default: 1.0,
        selector: { number: { min: 0.0625, max: 2.0, step: 0.0625, mode: 'slider' } }
      },
      {
        name: 'temp_size', default: 2.5,
        selector: { number: { min: 1.5, max: 7.5, step: 0.0625, mode: 'slider' } }
      },
      {
        name: 'info_size', default: 0.875,
        selector: { number: { min: 0.625, max: 3.0, step: 0.0625, mode: 'slider' } }
      }
    ];
  }

  _computeLabel(schema) {
    const labels = {
      entity: 'Gerät auswählen',
      name: 'Anzeigename (optional)',
      design: 'Design-Variante',
      color: 'Akzentfarbe',
      ac_trans: "Transparent",
      backcolor_system: 'Hintergrundfarbe System',
      textcolor_system: 'Textfarbe System',
      backcolor_light: 'Hintergrund Hell',
      backcolor_dark: 'Hintergrund Dunkel',
      textcolor_light: 'Textfarbe Hell',
      textcolor_dark: 'Textfarbe Dunkel',
      padding: 'Abstand (px)',
      temp_size: 'Temperatur (rem)',
      title_size: 'Titel (rem)',
      info_size: 'Info (rem)'
    };
    return labels[schema.name] || schema.name;
  }

  render() {
    if (!this._hass || this._rendered) return;
    this._rendered = true;

    const container = document.createElement('div');
    container.style.padding = '16px';
    this.appendChild(container);

    const form = document.createElement('ha-form');
    form.hass = this._hass;
    form.schema = this._getSchema();
    form.computeLabel = this._computeLabel.bind(this);
    
    // WICHTIG: data NACH schema setzen, damit die Werte korrekt vorbelegt werden
    setTimeout(() => {
      form.data = this._getFormData();
      // console.log('Form Data:', form.data); // Debug-Ausgabe
    }, 0);
    
   
    container.appendChild(form);

    // Lausche auf value-changed für alle Updates
    form.addEventListener('value-changed', (ev) => {
      ev.stopPropagation();
      if (!ev.detail || !ev.detail.value) return;
      
      // Tiefe Kopie über JSON
      const formData = JSON.parse(JSON.stringify(ev.detail.value));
      
      // RGB Array zu Hex konvertieren für Akzentfarbe
      if (formData.color && Array.isArray(formData.color) && formData.color.length === 3) {
        formData.color = this._rgbToHex(formData.color[0], formData.color[1], formData.color[2]);
      }
      
      // RGB Array zu Hex konvertieren für Hintergrundfarbe
      if (formData.backcolor_light && Array.isArray(formData.backcolor_light) && formData.backcolor_light.length === 3) {
        formData.backcolor_light = this._rgbToHex(formData.backcolor_light[0], formData.backcolor_light[1], formData.backcolor_light[2]);
      }
     
      // RGB Array zu Hex konvertieren für Hintergrundfarbe Dunkel
      if (formData.backcolor_dark && Array.isArray(formData.backcolor_dark) && formData.backcolor_dark.length === 3) {
        formData.backcolor_dark = this._rgbToHex(formData.backcolor_dark[0], formData.backcolor_dark[1], formData.backcolor_dark[2]);
      }      

      // RGB Array zu Hex konvertieren für Textfarbe
      if (formData.textcolor_light && Array.isArray(formData.textcolor_light) && formData.textcolor_light.length === 3) {
        formData.textcolor_light = this._rgbToHex(formData.textcolor_light[0], formData.textcolor_light[1], formData.textcolor_light[2]);
      }
     
      // RGB Array zu Hex konvertieren für Textfarbe Dunkel
      if (formData.textcolor_dark && Array.isArray(formData.textcolor_dark) && formData.textcolor_dark.length === 3) {
        formData.textcolor_dark = this._rgbToHex(formData.textcolor_dark[0], formData.textcolor_dark[1], formData.textcolor_dark[2]);
      }    

      // Config komplett neu erstellen
      this._config = { ...this._config, ...formData };
      
      // console.info('[HeatzoneCard] Aktuelle Konfiguration nach rows:auto :', this._config);

      this.dispatchEvent(new CustomEvent('config-changed', { 
        detail: { config: this._config },
        bubbles: true,
        composed: true
      }));
    });

    // Für Realtime Slider und Color Updates
    form.addEventListener('input', (ev) => {
      const path = ev.composedPath();
      let sliderValue = null;
      let colorValue = null;
      let fieldName = null;
      
      // Finde ha-slider und dessen Wert
      for (const el of path) {
        if (el.tagName === 'HA-SLIDER' && sliderValue === null) {
          sliderValue = parseFloat(el.value);
        }
        // Finde ha-color-picker für Farben (color UND backcolor_light)
        if (el.tagName === 'HA-COLOR-PICKER' && colorValue === null && el.value) {
          if (Array.isArray(el.value) && el.value.length === 3) {
            colorValue = this._rgbToHex(el.value[0], el.value[1], el.value[2]);
          }
        }
        // Finde ha-selector für den Feldnamen
        if (el.tagName === 'HA-SELECTOR' && !fieldName) {
          fieldName = el.name;
        }
      }
      
      if (fieldName) {
        if (sliderValue !== null && !isNaN(sliderValue)) {
          // Config direkt updaten für Slider
          this._config = { ...this._config, [fieldName]: sliderValue };
    
          this.dispatchEvent(new CustomEvent('config-changed', { 
            detail: { config: this._config },
            bubbles: true,
            composed: true
          }));
        } else if (colorValue !== null) {
          // Config direkt updaten für Farben (color UND backcolor_light)
          this._config = { ...this._config, [fieldName]: colorValue };

          this.dispatchEvent(new CustomEvent('config-changed', { 
            detail: { config: this._config },
            bubbles: true,
            composed: true
          }));
        }
      }
    });
  }
}

customElements.define('heatzone-card', HeatzoneCard);
customElements.define('heatzone-card-editor', HeatzoneCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'heatzone-card',
  name: 'Heatzone Card',
  description: 'Custom card für Heatzone Integration mit Konfigurations-Editor',
  preview: true,
  documentationURL: 'https://github.com/yourusername/heatzone-card'
});

console.info(
  '%c HEATZONE-CARD %c Version 0.9.0 HA-Form Realtime ',
  'color: white; background: #ff8c00; font-weight: 700;',
  'color: #ff8c00; background: white; font-weight: 700;'
);