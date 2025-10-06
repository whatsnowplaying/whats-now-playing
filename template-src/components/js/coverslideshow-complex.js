// Cover Slideshow - Complex Implementation
class CoverSlideshow {
    constructor() {
        this.currentTrack = null;
        this.coverImages = [];
        this.currentImageIndex = 0;
        this.slideshowInterval = null;
        this.fetchInterval = null;
        this.trackWsClient = null;
        this.imagesWs = null;
        this.slideshowDelay = 5000; // 5 seconds between images
        this.fetchDelay = 30000; // 30 seconds between fetch attempts
        this.debugMode = false;
    }

    log(message) {
        console.log(`[CoverSlideshow] ${message}`);
        if (this.debugMode) {
            const debugInfo = document.getElementById('debug-info');
            debugInfo.style.display = 'block';
            debugInfo.innerHTML += new Date().toLocaleTimeString() + ': ' + message + '<br>';
            debugInfo.scrollTop = debugInfo.scrollHeight;
        }
    }

    async startTrackWebSocket() {
        // Use WhatsNowPlayingWebSocket library for enhanced session tracking
        const templateVars = {
            session_id: "{{session_id}}",
            hostip: "{{hostip}}",
            httpport: {{httpport}}
        };

        this.trackWsClient = WhatsNowPlayingStreamers.createMetadataStreamer(templateVars, (metadata) => {
            if (metadata.last) {
                this.log('Received last message from track WebSocket');
                return;
            }

            const newTrack = {
                artist: metadata.artist,
                albumartist: metadata.albumartist,
                album: metadata.album,
                title: metadata.title,
                // Use albumartist for cover lookups if available, otherwise fall back to artist
                coverArtist: metadata.albumartist || metadata.artist
            };

            // Check if track changed
            if (!this.currentTrack ||
                this.currentTrack.artist !== newTrack.artist ||
                this.currentTrack.albumartist !== newTrack.albumartist ||
                this.currentTrack.album !== newTrack.album) {
                this.log(`New track: ${newTrack.artist} - ${newTrack.album}`);
                if (newTrack.albumartist && newTrack.albumartist !== newTrack.artist) {
                    this.log(`Using albumartist for covers: ${newTrack.albumartist}`);
                }
                this.currentTrack = newTrack;
                this.fetchCoverImages();
            }
        }, {
            debug: false,
            onOpen: () => { this.log('Track WebSocket connected via library'); },
            onClose: () => { this.log('Track WebSocket disconnected via library'); }
        });
    }

    async startImagesWebSocket() {
        const wsUrl = "ws://{{hostip}}:{{httpport}}/v1/images/ws";
        this.log(`Connecting to Images WebSocket: ${wsUrl}`);

        this.imagesWs = new WebSocket(wsUrl);

        this.imagesWs.onopen = () => {
            this.log('Images WebSocket connected');
            // Send hello message
            this.imagesWs.send(JSON.stringify({
                type: "hello"
            }));
        };

        this.imagesWs.onmessage = (event) => {
            const response = JSON.parse(event.data);
            this.handleImagesResponse(response);
        };

        this.imagesWs.onclose = () => {
            this.log('Images WebSocket disconnected, reconnecting in 5 seconds');
            setTimeout(() => this.startImagesWebSocket(), 5000);
        };

        this.imagesWs.onerror = (error) => {
            this.log(`Images WebSocket error: ${error}`);
        };
    }

    handleImagesResponse(response) {
        switch (response.type) {
            case 'welcome':
                this.log(`Images API ready: ${response.server} v${response.version}`);
                break;
            case 'image_data':
                if (response.data_type === 'album' && response.category === 'cover') {
                    this.addCoverImage(response.image_data, response.artist, response.album);
                }
                break;
            case 'no_image':
                this.log(`No cover images for: ${response.artist} - ${response.album}`);
                break;
            case 'error':
                this.log(`Images API error: ${response.error_code} - ${response.message}`);
                break;
            default:
                this.log(`Unknown response type: ${response.type}`);
        }
    }

    fetchCoverImages() {
        if (!this.currentTrack || !this.currentTrack.coverArtist || !this.currentTrack.album) {
            this.log('No current track data for fetching covers');
            return;
        }

        if (!this.imagesWs || this.imagesWs.readyState !== WebSocket.OPEN) {
            this.log('Images WebSocket not ready');
            return;
        }

        this.log(`Fetching covers for: ${this.currentTrack.coverArtist} - ${this.currentTrack.album}`);

        // Clear existing images
        this.coverImages = [];
        this.currentImageIndex = 0;
        document.getElementById('cover-container').innerHTML = '';

        // Request cover images multiple times to get different ones
        for (let i = 0; i < 5; i++) {
            setTimeout(() => {
                this.imagesWs.send(JSON.stringify({
                    type: "get_images",
                    data_type: "album",
                    category: "cover",
                    parameters: {
                        artist: this.currentTrack.coverArtist,
                        album: this.currentTrack.album
                    }
                }));
            }, i * 500); // Stagger requests by 500ms
        }
    }

    addCoverImage(imageData, artist, album) {
        // Check for duplicates
        if (this.coverImages.some(img => img.data === imageData)) {
            this.log('Duplicate image detected, skipping');
            return;
        }

        const imgElement = document.createElement('img');
        imgElement.className = 'cover-image';
        imgElement.src = `data:image/png;base64,${imageData}`;
        imgElement.style.opacity = '0';

        // Add load event listener for debugging
        imgElement.onload = () => {
            this.log(`Image loaded successfully: ${imgElement.naturalWidth}x${imgElement.naturalHeight}`);
        };
        imgElement.onerror = (error) => {
            this.log(`Image load error: ${error}`);
        };

        const coverData = {
            element: imgElement,
            data: imageData,
            artist: artist,
            album: album
        };

        this.coverImages.push(coverData);
        document.getElementById('cover-container').appendChild(imgElement);

        this.log(`Added cover image ${this.coverImages.length} for ${artist} - ${album}`);
        this.log(`Image element added to DOM with src length: ${imgElement.src.length}`);

        // Start slideshow if this is the first image
        if (this.coverImages.length === 1) {
            this.startSlideshow();
        }
    }

    startSlideshow() {
        if (this.slideshowInterval) {
            clearInterval(this.slideshowInterval);
        }

        if (this.coverImages.length === 0) {
            this.log('No images for slideshow');
            return;
        }

        // Show first image immediately
        this.showImage(0);

        if (this.coverImages.length > 1) {
            this.log(`Starting slideshow with ${this.coverImages.length} images`);
            this.slideshowInterval = setInterval(() => {
                this.nextImage();
            }, this.slideshowDelay);
        } else {
            this.log('Only one image, no slideshow needed');
        }
    }

    showImage(index) {
        if (index < 0 || index >= this.coverImages.length) {
            this.log(`Invalid image index: ${index} (total: ${this.coverImages.length})`);
            return;
        }

        // Hide all images
        this.coverImages.forEach((img, i) => {
            img.element.classList.remove('active');
            this.log(`Hidden image ${i + 1}, opacity: ${getComputedStyle(img.element).opacity}`);
        });

        // Show current image
        this.coverImages[index].element.classList.add('active');
        this.currentImageIndex = index;

        this.log(`Showing image ${index + 1}/${this.coverImages.length}`);

        // Check opacity after transition has time to start
        setTimeout(() => {
            this.log(`Active image opacity after transition: ${getComputedStyle(this.coverImages[index].element).opacity}`);
            this.log(`Active image dimensions: ${this.coverImages[index].element.offsetWidth}x${this.coverImages[index].element.offsetHeight}`);
        }, 100);
    }

    nextImage() {
        const nextIndex = (this.currentImageIndex + 1) % this.coverImages.length;
        this.showImage(nextIndex);
    }

    start() {
        this.log('Starting Cover Slideshow');

        // Enable debug mode with URL parameter
        const urlParams = new URLSearchParams(window.location.search);
        this.debugMode = urlParams.get('debug') === 'true';

        this.startTrackWebSocket();
        this.startImagesWebSocket();
    }
}

// Start when page loads
if ("WebSocket" in window) {
    const slideshow = new CoverSlideshow();
    slideshow.start();
} else {
    console.error('WebSocket not supported');
}