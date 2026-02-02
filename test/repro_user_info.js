
try {
    const os = require('os');
    console.log("Starting user info check...");
    const info = os.userInfo();
    console.log("Success:", info);
} catch (error) {
    console.error("Error:", error);
}
