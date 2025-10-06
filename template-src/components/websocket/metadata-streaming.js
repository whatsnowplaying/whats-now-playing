// WebSocket Setup for Metadata Streaming
const templateVars = {
    session_id: "{{session_id}}",
    hostip: "{{hostip}}",
    httpport: {{httpport}}
};

// Check for debug parameter in URL
const urlParams = new URLSearchParams(window.location.search);
const debugMode = urlParams.get('debug') === 'true';

const wsClient = WhatsNowPlayingStreamers.createMetadataStreamer(templateVars, updateDisplay, {
    debug: debugMode,
    reconnectDelay: 3000,  // Reconnect after 3 seconds
    maxReconnectAttempts: -1,  // Infinite reconnection attempts
    onOpen: function() {
        console.log('WebSocket connected');
    },
    onClose: function() {
        console.log('WebSocket disconnected, will attempt to reconnect...');
    },
    onError: function(error) {
        console.log('WebSocket error:', error);
    }
});