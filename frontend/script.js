document.getElementById("helloBtn").addEventListener("click", async () => {
    const res = await fetch("/api/hello");
    const data = await res.json();
    document.getElementById("output").innerText = data.message;
});
