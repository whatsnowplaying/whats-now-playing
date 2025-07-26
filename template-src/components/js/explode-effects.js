// Anime.js Explode Effects for Templates
// This modifies the updateDisplay function to add anime.js explode animations

// Destructure animate function from the global anime object
const { animate } = anime;

// Store the original updateDisplay function
const originalUpdateDisplay = updateDisplay;

// Override updateDisplay with anime.js explode effects
updateDisplay = function(metadata) {
    // Call the original display function first
    originalUpdateDisplay(metadata);

    // Add explode animation if there's content
    if (metadata.title) {
        // Show content normally for 8 seconds, then explode
        setTimeout(function() {
            // Animate title and artist flying in different directions
            animate('#titlecard .title', {
                translateX: [-200, -400],
                translateY: [0, -200],
                rotate: [0, -180],
                scale: [1, 0.3],
                opacity: [1, 0],
                duration: 2000,
                ease: 'outQuart'
            });

            animate('#titlecard .artist', {
                translateX: [200, 400],
                translateY: [0, 200],
                rotate: [0, 180],
                scale: [1, 0.3],
                opacity: [1, 0],
                duration: 2000,
                delay: 100,
                ease: 'outQuart'
            });
        }, 8000);
    }
};