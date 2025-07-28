// Anime.js v4 Bounce Effects for Templates
// This modifies the updateDisplay function to add bouncy animations

// Destructure animate function from the global anime object
const { animate } = anime;

// Store the original updateDisplay function
const originalUpdateDisplay = updateDisplay;

// Override updateDisplay with bouncy anime.js v4 effects
updateDisplay = function(metadata) {
    // Call the original display function first
    originalUpdateDisplay(metadata);

    // Add bouncy animation if there's content
    if (metadata.title) {
        // Simple bounce-in from top
        animate('#titlecard', {
            translateY: [-200, 0],
            opacity: [0, 1],
            scale: [0.8, 1.1, 1],
            duration: 1200,
            ease: 'outBounce'
        });

        // Continuous gentle bounce every 4 seconds
        setTimeout(function() {
            animate('#titlecard', {
                translateY: [0, -20, 0],
                duration: 800,
                ease: 'inOutBounce',
                loop: true,
                delay: 4000
            });
        }, 2000);
    }
};