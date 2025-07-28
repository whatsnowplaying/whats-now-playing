// Slide Down/Up Effects for Templates
// This modifies the updateDisplay function to add slide effects

// Store the original updateDisplay function
const originalUpdateDisplay = updateDisplay;

// Override updateDisplay with slide effects
updateDisplay = function(metadata) {
    // Hide and slide up first
    $('#titlecard').slideUp();

    // Call the original display function
    originalUpdateDisplay(metadata);

    // Slide down if there's content
    if (metadata.title) {
        $('#titlecard').delay(500).slideDown();
    }
};