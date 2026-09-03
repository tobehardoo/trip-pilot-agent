package io.github.tobehardoo.trippilot.trip;

import io.github.tobehardoo.trippilot.agentdialog.HttpAgentDialogClient;
import java.util.List;
import java.util.Map;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Composer Required Context 种子（2026-09-02 design D1）：创建对话首轮必须把
 * 嵌套 tripContext（与 web/Python 契约一致）透传为 TRIP 事实上下文；
 * 缺省或目的地为空时上下文为 null（空白开始）。
 */
class TripAgentCreateControllerTest {

    /** 捕获 createDialogue 命令的 fake（工程约定：不引入 mock 框架）。 */
    private static final class CapturingDialogClient extends HttpAgentDialogClient {
        AgentCreateDialogCommand captured;

        CapturingDialogClient() {
            super(RestClient.builder(), "http://agent.test", "internal-token", 1);
        }

        @Override
        public AgentDialogReply createDialogue(AgentCreateDialogCommand command) {
            this.captured = command;
            return new AgentDialogReply("COLLECTING", false, List.of(), Map.of());
        }
    }

    private CapturingDialogClient client;
    private TripAgentCreateController controller;

    @org.junit.jupiter.api.BeforeEach
    void setUp() {
        client = new CapturingDialogClient();
        controller = new TripAgentCreateController(null, client, null);
    }

    @org.junit.jupiter.api.Test
    void dialogueForwardsRequiredContextAsTripFacts() {
        var request = new TripAgentCreateController.CreateDialogRequest(
                "session-1",
                "想轻松一点",
                null,
                false,
                new HttpAgentDialogClient.TripContext("广州", "2026-09-10", "2026-09-13"));

        controller.dialogue(null, request);

        assertThat(client.captured).isNotNull();
        assertThat(client.captured.sessionId()).isEqualTo("session-1");
        assertThat(client.captured.message()).isEqualTo("想轻松一点");
        assertThat(client.captured.tripContext()).isNotNull();
        assertThat(client.captured.tripContext().destination()).isEqualTo("广州");
        assertThat(client.captured.tripContext().startDate()).isEqualTo("2026-09-10");
        assertThat(client.captured.tripContext().endDate()).isEqualTo("2026-09-13");
    }

    @org.junit.jupiter.api.Test
    void dialogueWithoutContextStartsFromBlankSlate() {
        var request = new TripAgentCreateController.CreateDialogRequest(
                "session-2", null, null, null, null);

        controller.dialogue(null, request);

        assertThat(client.captured).isNotNull();
        assertThat(client.captured.tripContext()).isNull();
    }

    @org.junit.jupiter.api.Test
    void dialogueForwardsTravelersAndBudgetFromContext() {
        var request = new TripAgentCreateController.CreateDialogRequest(
                "session-4",
                "两个人，预算一万",
                null,
                false,
                new HttpAgentDialogClient.TripContext("广州", "2026-09-10", "2026-09-13", 2, 10000));

        controller.dialogue(null, request);

        assertThat(client.captured).isNotNull();
        assertThat(client.captured.tripContext()).isNotNull();
        assertThat(client.captured.tripContext().travelers()).isEqualTo(2);
        assertThat(client.captured.tripContext().budgetAmount()).isEqualTo(10000);
    }

    @org.junit.jupiter.api.Test
    void dialogueWithBlankDestinationStartsFromBlankSlate() {
        var request = new TripAgentCreateController.CreateDialogRequest(
                "session-3",
                "你好",
                null,
                null,
                new HttpAgentDialogClient.TripContext("  ", "2026-09-10", "2026-09-13"));

        controller.dialogue(null, request);

        assertThat(client.captured).isNotNull();
        assertThat(client.captured.tripContext()).isNull();
    }
}
