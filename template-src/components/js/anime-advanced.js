// Advanced Anime.js v4 Effects
// Destructure functions from the global anime object
const { animate, stagger, utils } = anime;

// Store the original updateDisplay function
const originalUpdateDisplay = updateDisplay;

// Override updateDisplay with advanced anime.js v4 effects
updateDisplay = function(metadata) {
    // Stagger out animation for existing content
    animate('#titlecard .title, #titlecard .artist', {
        translateX: -100,
        opacity: 0,
        duration: 400,
        delay: stagger(100),
        ease: 'inBack',
        onComplete: function() {
            // Call the original display function
            originalUpdateDisplay(metadata);

            // Animate in new content if present
            if (metadata.title) {
                // Reset positions
                utils.set('#titlecard .title, #titlecard .artist', {
                    translateX: 100,
                    opacity: 0
                });

                // Stagger in animation
                animate('#titlecard .title, #titlecard .artist', {
                    translateX: 0,
                    opacity: 1,
                    duration: 600,
                    delay: stagger(150, 300),
                    ease: 'outBack(1.7)'
                });

                // Pulse animation every 3 seconds
                const pulseAnimation = animate('#titlecard', {
                    scale: [1, 1.05, 1],
                    duration: 1000,
                    ease: 'inOutSine',
                    loop: true,
                    delay: 2000
                });

                // Stop pulse and fade out after 10 seconds
                setTimeout(function() {
                    pulseAnimation.pause();
                    animate('#titlecard', {
                        scale: 1,
                        opacity: 0,
                        duration: 800,
                        ease: 'inOutQuart'
                    });
                }, 10000);
            }
        }
    });
};