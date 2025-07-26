// Anime.js v4 Effects for Templates
// This modifies the updateDisplay function to add anime.js v4 animations

// Destructure animate function from the global anime object
const { animate } = anime;

// Store the original updateDisplay function
const originalUpdateDisplay = updateDisplay;

// Override updateDisplay with anime.js v4 effects
updateDisplay = function(metadata) {
    // Call the original display function first
    originalUpdateDisplay(metadata);

    // Add dramatic animation if there's content
    if (metadata.title) {
        // Start from very small and bounce in dramatically
        animate('#titlecard', {
            scale: [0.1, 1.2, 1],
            opacity: [0, 1],
            rotate: [0, 10, 0],
            duration: 1500,
            ease: 'outElastic(1, .6)'
        });

        // Pulse effect every 3 seconds
        setTimeout(function() {
            animate('#titlecard', {
                scale: [1, 1.1, 1],
                duration: 600,
                ease: 'inOutQuad',
                loop: true,
                delay: 3000
            });
        }, 2000);
    }
};