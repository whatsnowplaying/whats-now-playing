/**
 * Now Playing WebSocket Client Library
 * Provides enhanced session tracking, OBS integration, and WebSocket management
 */
class NowPlayingWebSocket {
    constructor(options = {}) {
        this.sessionId = options.sessionId || 'unknown';
        this.hostIp = options.hostIp || 'localhost';
        this.httpPort = options.httpPort || 8899;
        this.endpoint = options.endpoint || '/wsstream';
        this.reconnectDelay = options.reconnectDelay || 5000;
        this.debugMode = options.debug || false;

        this.ws = null;
        this.sceneName = 'unknown';
        this.isConnected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = options.maxReconnectAttempts || -1; // -1 = infinite

        // Callbacks
        this.onMessage = options.onMessage || this.defaultOnMessage.bind(this);
        this.onOpen = options.onOpen || this.defaultOnOpen.bind(this);
        this.onClose = options.onClose || this.defaultOnClose.bind(this);
        this.onError = options.onError || this.defaultOnError.bind(this);

        this.init();
    }

    init() {
        this.detectOBSScene();
        this.connect();
    }

    detectOBSScene() {
        if (window.obsstudio && window.obsstudio.getCurrentScene) {
            window.obsstudio.getCurrentScene((scene) => {
                this.sceneName = scene.name;
                this.log(`OBS Scene detected: ${this.sceneName}`);
            });

            // Listen for scene changes
            window.addEventListener('obsSceneChanged', (event) => {
                this.sceneName = event.detail.name;
                this.log(`Scene changed to: ${this.sceneName}`);
            });
        } else {
            this.log('OBS browser bindings not available - running outside OBS or old version');
        }
    }

    connect() {
        if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
            this.log('WebSocket already connecting or connected');
            return;
        }

        const wsUrl = `ws://${this.hostIp}:${this.httpPort}${this.endpoint}?session_id=${this.sessionId}`;
        this.log(`Connecting to ${wsUrl} from scene: ${this.sceneName}`);

        try {
            this.ws = new WebSocket(wsUrl);
            this.ws.onopen = this.handleOpen.bind(this);
            this.ws.onmessage = this.handleMessage.bind(this);
            this.ws.onclose = this.handleClose.bind(this);
            this.ws.onerror = this.handleError.bind(this);
        } catch (error) {
            this.log(`WebSocket connection error: ${error}`);
            this.scheduleReconnect();
        }
    }

    handleOpen(event) {
        this.isConnected = true;
        this.reconnectAttempts = 0;
        this.log(`WebSocket connected (session: ${this.sessionId}, scene: ${this.sceneName})`);
        this.onOpen(event);
    }

    handleMessage(event) {
        try {
            const data = JSON.parse(event.data);
            if (data.last) {
                this.log('Received last message from server');
                return;
            }
            this.onMessage(data, event);
        } catch (error) {
            this.log(`Error parsing message: ${error}`);
        }
    }

    handleClose(event) {
        this.isConnected = false;
        this.log(`WebSocket disconnected (session: ${this.sessionId}, scene: ${this.sceneName}, code: ${event.code})`);
        this.onClose(event);
        this.scheduleReconnect();
    }

    handleError(event) {
        this.log(`WebSocket error (session: ${this.sessionId}, scene: ${this.sceneName}): ${event}`);
        this.onError(event);
    }

    scheduleReconnect() {
        if (this.maxReconnectAttempts > 0 && this.reconnectAttempts >= this.maxReconnectAttempts) {
            this.log(`Max reconnection attempts (${this.maxReconnectAttempts}) reached`);
            return;
        }

        this.reconnectAttempts++;
        this.log(`Scheduling reconnection attempt ${this.reconnectAttempts} in ${this.reconnectDelay}ms`);

        setTimeout(() => {
            this.connect();
        }, this.reconnectDelay);
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
            return true;
        } else {
            this.log('Cannot send data - WebSocket not connected');
            return false;
        }
    }

    close() {
        if (this.ws) {
            this.ws.close();
        }
    }

    log(message) {
        const timestamp = new Date().toLocaleTimeString();
        const logMessage = `[${timestamp}] [NowPlayingWS] ${message}`;
        console.log(logMessage);

        if (this.debugMode) {
            // Could add visual debug display here
        }
    }

    // Default event handlers (can be overridden)
    defaultOnOpen(event) {
        // Override in options or subclass
    }

    defaultOnMessage(data, event) {
        // Override in options or subclass
        this.log(`Received data: ${JSON.stringify(data).substring(0, 100)}...`);
    }

    defaultOnClose(event) {
        // Override in options or subclass
    }

    defaultOnError(event) {
        // Override in options or subclass
    }

    // Static helper for creating WebSocket with template variables
    static createFromTemplate(templateVars, options = {}) {
        const config = {
            sessionId: templateVars.session_id,
            hostIp: templateVars.hostip,
            httpPort: templateVars.httpport,
            ...options
        };
        return new NowPlayingWebSocket(config);
    }
}

/**
 * Specialized WebSocket client for different stream types
 */
class NowPlayingStreamers {
    // Standard metadata streamer
    static createMetadataStreamer(templateVars, onMessage, options = {}) {
        return NowPlayingWebSocket.createFromTemplate(templateVars, {
            endpoint: '/wsstream',
            onMessage: onMessage,
            ...options
        });
    }

    // Artist fanart streamer
    static createArtistFanartStreamer(templateVars, onMessage, options = {}) {
        return NowPlayingWebSocket.createFromTemplate(templateVars, {
            endpoint: '/wsartistfanartstream',
            onMessage: onMessage,
            ...options
        });
    }

    // Gifwords streamer
    static createGifwordsStreamer(templateVars, onMessage, options = {}) {
        return NowPlayingWebSocket.createFromTemplate(templateVars, {
            endpoint: '/wsgifwordsstream',
            onMessage: onMessage,
            ...options
        });
    }

    // Images WebSocket streamer
    static createImagesStreamer(templateVars, onMessage, options = {}) {
        return NowPlayingWebSocket.createFromTemplate(templateVars, {
            endpoint: '/v1/images/ws',
            onMessage: onMessage,
            ...options
        });
    }
}

// Export for both CommonJS and browser globals
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { NowPlayingWebSocket, NowPlayingStreamers };
} else {
    window.NowPlayingWebSocket = NowPlayingWebSocket;
    window.NowPlayingStreamers = NowPlayingStreamers;
}