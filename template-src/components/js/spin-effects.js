// Anime.js Spin Effects for Templates
// This modifies the updateDisplay function to add anime.js spin animations

// Destructure animate function from the global anime object
const { animate } = anime;

// Store the original updateDisplay function
const originalUpdateDisplay = updateDisplay;

// Override updateDisplay with anime.js spin effects
updateDisplay = function(metadata) {
    // Call the original display function first
    originalUpdateDisplay(metadata);

    // Add spin animation if there's content
    if (metadata.title) {
        // Show content normally for 8 seconds, then spin away
        setTimeout(function() {
            animate('#titlecard', {
                scale: [1, 0.1],
                rotate: [0, 720],
                opacity: [1, 0],
                duration: 2000,
                ease: 'inQuart'
            });
        }, 8000);
    }
};