package io.github.tobehardoo.trippilot.agentdialog;

import io.github.tobehardoo.trippilot.infrastructure.mq.AgentAskUserEvent;
import io.github.tobehardoo.trippilot.infrastructure.mq.AgentCompletedEvent;
import io.github.tobehardoo.trippilot.infrastructure.mq.AgentRunFinishedEvent;
import io.github.tobehardoo.trippilot.infrastructure.mq.AgentStepEvent;

/** Application-side handler for the agent dialog event family. */
public interface AgentDialogEventHandler {

    void handleAskUser(AgentAskUserEvent event);

    void handleStep(AgentStepEvent event);

    void handleCompleted(AgentCompletedEvent event);

    void handleRunFinished(AgentRunFinishedEvent event);
}
