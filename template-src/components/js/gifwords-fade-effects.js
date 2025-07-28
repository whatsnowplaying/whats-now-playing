// GIF Words Fade Effects
// This modifies the updateDisplay function to add fade effects

// Store the original updateDisplay function
const originalUpdateDisplay = updateDisplay;

// Override updateDisplay with fade effects
updateDisplay = function(metadata) {
    $('#gifwordsart').hide();

    // Call the original display function
    originalUpdateDisplay(metadata);

    // Add fade effects if there's content
    if (metadata.imagebase64) {
        $('#gifwordsart').delay(200).fadeIn(200);
        $('#gifwordsart').delay(10000).fadeOut(200);
    }
};