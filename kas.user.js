// ==UserScript==
// @name        Komp Apple Script
// @description Script for Apples.
// @author      komp
// @version     1.0
// @namespace   KAS
// @match       https://en.gamesaien.com/game/fruit_box/*
// @match       https://gamesaien.com/game/fruit_box/*
// @match       https://www.gamesaien.com/game/fruit_box/*
// @grant       none
// @run-at      document-idle
// @license     GPL-3.0-or-later
// ==/UserScript==

(() => {

    "use strict"

    // ClientInfo: {
    //     "name": string,
    //     "version": int
    // }
    // History: {
    //     version: int,
    //     lastUpdated: date,
    //     attempts: []Attempt
    // }
    // Attempt: {
    //     started: date,
    //     ended: date,
    //     score: int,
    //     finished: bool,
    //     perfect: bool,
    //     duration: float
    // }
    // Progress: {
    //     score: int,
    //     timeRemaining: float
    // }

    let KAS_DelayedInitTimerId = -1;
    let KAS_TickTimerId = -1;
    let KAS_Debug = false;
    let KAS_Socket = null;
    let KAS_RemoteStatus = 0;
    let KAS_RetryCount = 0;
    let KAS_TickInterval = 100;
    let KAS_ProgressTimer = 0;
    let KAS_TimeElapsed = 0;
    let KAS_Attempt = null;
    let KAS_Progress = null;
    let KAS_Version = 1;

    function tryConnectToServer() {
        if (KAS_RemoteStatus == 1 || KAS_Socket != null) {
            return;
        }

        KAS_Socket = new WebSocket("ws://localhost:8765");

        KAS_Socket.onopen = function (event) {
            log_dbg("Connected to remote server.");
            KAS_RemoteStatus = 1;
            KAS_RetryCount = 0;

            sendClientInfo();
            syncHistory();
        };

        KAS_Socket.onmessage = function (event) {
            log_dbg("Received message: ", event.data);
        };

        KAS_Socket.onclose = function (event) {
            if (KAS_RemoteStatus == 1) {
                log_dbg("Disconnected with server.");
                KAS_Socket = null;
                KAS_RemoteStatus = 0;
            }
        };

        KAS_Socket.onerror = function (event) {
            if (KAS_RemoteStatus == 0) {
                log_dbg("Failed to connect to server, will retry on Reset!");
            }
            KAS_Socket.close();
            KAS_Socket = null;
            KAS_RemoteStatus = 0;
        };
    }

    function sendToServer(msg, obj) {
        if (KAS_Socket != null && KAS_RemoteStatus == 1) {
            const payload = new Object();
            payload.msg = msg;
            payload.data = obj;
            KAS_Socket.send(JSON.stringify(payload));
        }
    }

    function sendClientInfo() {
        const client = new Object();
        client.name = "apple";
        client.version = KAS_Version;
        sendToServer("clientInfo", client);
    }

    function syncHistory() {
        sendToServer("history", getHistory());
    }

    function initHistory() {
        const history = {};
        history.version = KAS_Version;
        history.lastUpdated = Date.now();
        history.attempts = [];
        return history;
    }

    function getHistory() {
        var history = JSON.parse(localStorage.getItem("KAS")) || initHistory();
        if (history.version < KAS_Version) {
            // Upgrade
        }
        return history;
    }

    function addAttemptToHistory(attempt) {
        log_dbg("addAttemptToHistory()");

        const history = getHistory();
        history.attempts.push(attempt);
        history.lastUpdated = Date.now();
        localStorage.setItem("KAS", JSON.stringify(history));
    }

    function startNewAttempt() {
        KAS_Attempt = new Object();
        KAS_Attempt.started = Date.now();
        KAS_Attempt.ended = null;
        KAS_Attempt.score = 0;
        KAS_Attempt.finished = false;
        KAS_Attempt.perfect = false;
        KAS_Attempt.duration = 0;

        KAS_Progress = new Object();
        KAS_Progress.score = 0;
        KAS_Progress.timeRemaining = 120;

        sendToServer("attemptStart", null);
        sendToServer("progress", KAS_Progress);

        KAS_TickTimerId = setInterval(tick, KAS_TickInterval);
        KAS_TimeElapsed = 0;
    }

    function finishAttempt(finished) {
        KAS_Attempt.ended = Date.now();
        KAS_Attempt.score = getPoints();
        KAS_Attempt.finished = finished;
        KAS_Attempt.perfect = isPerfectScore();
        KAS_Attempt.duration = (KAS_Attempt.ended - KAS_Attempt.started) / 1000;

        sendToServer("attemptEnd", KAS_Attempt);

        addAttemptToHistory(KAS_Attempt);

        clearInterval(KAS_TickTimerId);
        KAS_TickTimerId = -1;
        KAS_Attempt = null;
        KAS_Progress = null;
    }

    function updateProgress() {
        KAS_Progress.score = getPoints();
        KAS_Progress.timeRemaining = getRemainingTime();

        if (KAS_Progress.timeRemaining < 0.0) {
            KAS_Progress.timeRemaining = 0.0;
        }

        sendToServer("progress", KAS_Progress);
    }

    function onPlay() {
        log_dbg("onPlay()");
        startNewAttempt();
        tryConnectToServer();
    }

    function onReset() {
        log_dbg("onReset()");

        // We can press reset on main screen too!
        if (KAS_Attempt != null) {
            finishAttempt(false);
        }

        tryConnectToServer();
    }

    function onFinish() {
        log_dbg("onFinish()");
        finishAttempt(true);
    }

    function onTick() {
        //log_dbg("onTick()");

        //KAS_ProgressTimer += KAS_TickInterval;
        //KAS_TimeElapsed += KAS_TickInterval;

        //if (KAS_ProgressTimer > 1000) {
        //    updateProgress();
        //    KAS_ProgressTimer = 0;
        //}

        updateProgress();
    }

    function tick() {
        onTick();

        if (getRemainingTime() <= 0) {
            onFinish();
        }

        if (isPerfectScore()) {
            onFinish();
        }
    }

    function getPoints() {
        return window.stage.children[0].children[1].children[1].point;
    }

    function getRemainingTime() {
        return window.timeRemain;
    }

    function isPerfectScore() {
        return window.nuMbX * window.nuMbY == getPoints();
    }

    function getFruitBox() {
        const stage = window.stage;
        if (typeof stage === "undefined") {
            return null;
        }

        const fruit_box_a_006_o = stage.children[0];
        if (typeof fruit_box_a_006_o === "undefined") {
            return null;
        }

        log_dbg("FruitBox: ", fruit_box_a_006_o);

        return fruit_box_a_006_o;
    }

    function delayedInit() {
        const fruitBox = getFruitBox();

        if (fruitBox == null) return;
        if (typeof fruitBox.mzBtPlay === "undefined") return;
        if (typeof fruitBox.mzBtReset === "undefined") return;

        log_dbg("Adding event listenters...")

        fruitBox.mzBtPlay.addEventListener("click", function (e) {
            onPlay();
        });
        fruitBox.mzBtReset.addEventListener("click", function (e) {
            onReset();
        });

        clearInterval(KAS_DelayedInitTimerId);
        KAS_DelayedInitTimerId = -1;

        tryConnectToServer();

        log_dbg("Initialized.")
    }

    function init() {
        log_dbg("Initializing Komp Apple Script...");
        KAS_DelayedInitTimerId = setInterval(delayedInit, 100);
    }

    function log_dbg(msg) {
        if (KAS_Debug) {
            if (arguments.length > 1) {
                console.log(msg, arguments);
            } else {
                console.log(msg);
            }
        }
    }

    // Run script.
    init()

})()
