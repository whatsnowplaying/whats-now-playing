// Fade Effects for Templates
// This modifies the updateDisplay function to add fade in/out effects

// Store the original updateDisplay function
const originalUpdateDisplay = updateDisplay;

// Override updateDisplay with fade effects
updateDisplay = function(metadata) {
    $('#titlecard').hide();

    // Call the original display function
    originalUpdateDisplay(metadata);

    // Add fade effects if there's content
    if (metadata.title) {
        $('#titlecard').delay(2000).fadeIn(2000);
        $('#titlecard').delay(10000).fadeOut(2000);
    }
};