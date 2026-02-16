/* Typed.js effects with realistic mistakes for What's Now Playing */

class TypingEffects {
    constructor() {
        this.currentData = null;
        this.typedInstances = [];
        this.debugMode = new URLSearchParams(window.location.search).has('debug');

        // Common typing mistakes patterns
        this.mistakePatterns = [
            { from: 'the', to: 'teh' },
            { from: 'and', to: 'adn' },
            { from: 'you', to: 'yuo' },
            { from: 'ing', to: 'ign' },
            { from: 'tion', to: 'toin' },
            { from: 'er', to: 're' },
            { from: 'th', to: 'ht' },
            { from: 'he', to: 'eh' },
            { from: 'in', to: 'ni' },
            { from: 'on', to: 'no' }
        ];
    }

    init() {
        this.showDebugInfo('Typing effects initialized');
    }

    updateTypingContent(data) {
        // Only update if data has changed
        if (JSON.stringify(data) !== JSON.stringify(this.currentData)) {
            this.currentData = data;

            // Destroy existing typed instances
            this.typedInstances.forEach(instance => {
                if (instance && typeof instance.destroy === 'function') {
                    instance.destroy();
                }
            });
            this.typedInstances = [];

            // Build strings for typing
            const artistText = data.artist || '';
            const titleText = data.title || '';
            const albumText = data.album || '';

            if (artistText || titleText) {
                this.showDebugInfo(`Typing: ${artistText} - ${titleText}`);
                this.startTypingSequence(artistText, titleText, albumText);
            }
        }
    }

    startTypingSequence(artist, title, album) {
        // Clear existing content
        document.getElementById('artist-line').innerHTML = '';
        document.getElementById('title-line').innerHTML = '';
        document.getElementById('album-line').innerHTML = '';

        // Create typing sequence with delays
        let delay = 0;

        if (artist) {
            setTimeout(() => {
                this.typeWithMistakes('artist-line', `Artist: ${artist}`, {
                    typeSpeed: this.getRandomSpeed(50, 100),
                    backSpeed: 30,
                    backDelay: 1000,
                    showCursor: true,
                    cursorChar: '_',
                    onComplete: () => {
                        // Start title typing after artist is done
                        if (title) {
                            setTimeout(() => {
                                this.typeWithMistakes('title-line', `Title: ${title}`, {
                                    typeSpeed: this.getRandomSpeed(40, 90),
                                    backSpeed: 25,
                                    backDelay: 800,
                                    showCursor: true,
                                    cursorChar: '_',
                                    onComplete: () => {
                                        // Start album typing after title is done
                                        if (album) {
                                            setTimeout(() => {
                                                this.typeWithMistakes('album-line', `Album: ${album}`, {
                                                    typeSpeed: this.getRandomSpeed(60, 110),
                                                    backSpeed: 35,
                                                    backDelay: 600,
                                                    showCursor: false,
                                                    cursorChar: '_'
                                                });
                                            }, 500);
                                        }
                                    }
                                });
                            }, 800);
                        }
                    }
                });
            }, delay);
        } else if (title) {
            // If no artist, start with title
            setTimeout(() => {
                this.typeWithMistakes('title-line', `Now Playing: ${title}`, {
                    typeSpeed: this.getRandomSpeed(40, 90),
                    backSpeed: 25,
                    backDelay: 800,
                    showCursor: !!album,
                    cursorChar: '_',
                    onComplete: () => {
                        if (album) {
                            setTimeout(() => {
                                this.typeWithMistakes('album-line', `Album: ${album}`, {
                                    typeSpeed: this.getRandomSpeed(60, 110),
                                    backSpeed: 35,
                                    backDelay: 600,
                                    showCursor: false,
                                    cursorChar: '_'
                                });
                            }, 500);
                        }
                    }
                });
            }, delay);
        }
    }

    typeWithMistakes(elementId, text, options = {}) {
        const element = document.getElementById(elementId);
        if (!element) return;

        // Add mistakes to the text
        const textWithMistakes = this.addMistakes(text);

        const typedInstance = new Typed(`#${elementId}`, {
            strings: textWithMistakes,
            typeSpeed: options.typeSpeed || 70,
            backSpeed: options.backSpeed || 30,
            backDelay: options.backDelay || 1000,
            startDelay: options.startDelay || 0,
            showCursor: options.showCursor !== undefined ? options.showCursor : true,
            cursorChar: options.cursorChar || '|',
            loop: false,
            onComplete: options.onComplete || null
        });

        this.typedInstances.push(typedInstance);
        return typedInstance;
    }

    addMistakes(text) {
        const strings = [];
        let workingText = text;

        // Decide if we should add mistakes (30% chance)
        if (Math.random() < 0.3) {
            // Find a good place to add a mistake
            const words = workingText.split(' ');
            if (words.length > 1) {
                const wordIndex = Math.floor(Math.random() * words.length);
                const originalWord = words[wordIndex];

                // Try to find a matching mistake pattern
                let mistakeWord = originalWord;
                for (const pattern of this.mistakePatterns) {
                    if (originalWord.toLowerCase().includes(pattern.from)) {
                        mistakeWord = originalWord.toLowerCase().replace(pattern.from, pattern.to);
                        break;
                    }
                }

                // If no pattern matched, create a random transposition
                if (mistakeWord === originalWord && originalWord.length > 2) {
                    const chars = originalWord.split('');
                    const pos = Math.floor(Math.random() * (chars.length - 1));
                    [chars[pos], chars[pos + 1]] = [chars[pos + 1], chars[pos]];
                    mistakeWord = chars.join('');
                }

                if (mistakeWord !== originalWord) {
                    words[wordIndex] = mistakeWord;
                    const mistakeText = words.join(' ');

                    // Add the mistake version first
                    strings.push(mistakeText);
                    // Then add the corrected version
                    strings.push(text);

                    return strings;
                }
            }
        }

        // No mistakes, just type normally
        strings.push(text);
        return strings;
    }

    getRandomSpeed(min, max) {
        return Math.floor(Math.random() * (max - min + 1)) + min;
    }

    showDebugInfo(message) {
        if (!this.debugMode) return;

        let debugDiv = document.getElementById('debug-info');
        if (!debugDiv) {
            debugDiv = document.createElement('div');
            debugDiv.id = 'debug-info';
            debugDiv.className = 'debug-info';
            document.body.appendChild(debugDiv);
        }

        const timestamp = new Date().toLocaleTimeString();
        debugDiv.innerHTML += `<div>[${timestamp}] ${message}</div>`;

        // Keep only last 10 debug messages
        const messages = debugDiv.children;
        if (messages.length > 10) {
            debugDiv.removeChild(messages[0]);
        }

        // Auto-scroll to bottom
        debugDiv.scrollTop = debugDiv.scrollHeight;
    }
}

// Global instance for use with metadata-streaming component
let typingEffects;

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    typingEffects = new TypingEffects();
    typingEffects.init();
});

// Global updateDisplay function called by metadata-streaming component
function updateDisplay(data) {
    if (typingEffects) {
        typingEffects.updateTypingContent(data);
    }
}