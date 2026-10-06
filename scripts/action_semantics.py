"""Reviewed behavior of the 66 explicit map-entry selectors in the recovered set.

Labels describe observed behavior. They are not claimed to be original enum
spellings. Runtime requirements are retained rather than reporting completion.
"""


def definitions():
    result = {}

    def add(ids, label, category, mode, behavior, requires, evidence):
        for value in ids:
            result[str(value)] = dict(name=label, category=category, payloadMode=mode,
                                     behavior=behavior, requires=requires, evidence=evidence,
                                     status='source_traced', labelKind='behavior_description')

    runtime = ['simulation state determines acceptance and outcome']
    add([2472102578], 'command', 'gameplay_command', 'ability', 'Dispatch an ability order through the participant selection and command handlers.', runtime, 'on_action_shared B24')
    add([3322138414], 'command_queued', 'gameplay_command', 'ability', 'Collect eligible selection handlers with queued-command verb; skip entities whose order queue exceeds 31 entries.', runtime, 'on_action_shared B24/B66')
    add([1644040531], 'command_preempted', 'gameplay_command', 'ability', 'Enter the shared selection-command path with the preempted-command verb.', runtime, 'on_action_shared B24; UnitTask::on_action')
    add([2631289655], 'command_acquired', 'gameplay_command', 'ability', 'Enter the shared selection-command path with the acquired-command verb.', runtime, 'on_action_shared B24; UnitTask::on_action')
    add([1432744753], 'command_ai', 'gameplay_command', 'ability', 'Collect selected command handlers and forward the AI command payload.', runtime, 'on_action_shared B22; CommandAI diagnostic')
    add([2626128676], 'smart_command', 'gameplay_command', 'smart', 'Select context-sensitive handlers, including movement formation handling, and dispatch the smart order.', runtime+['selected units and target determine the actual ability'], 'on_action_shared B3; UnitTask::on_smart_command')
    add([307192056], 'smart_command_queued', 'gameplay_command', 'smart', 'Run smart selection dispatch with the queued variant.', runtime+['selected units and target determine the actual ability'], 'on_action_shared B3; UnitTask::on_smart_command')
    add([815962355], 'smart_command_to_entity', 'gameplay_command', 'single_smart', 'Check command permission for subject; data chooses normal versus queued smart verb and x/y provide position.', runtime, 'on_action_shared B21')
    add([81781465], 'quick_macro', 'gameplay_command', 'ability', 'Pass the action to QuickMacro::execute for the participant player slot.', runtime+['QuickMacro selects the acting unit dynamically'], 'on_action_shared; QuickMacro::execute')
    add([1304751467], 'quick_macro_smart', 'gameplay_command', 'smart', 'Pass the action to QuickMacro::execute_smart.', runtime+['context and eligible units determine the acting unit and ability'], 'on_action_shared B23')
    add([1756538168], 'drop_item_queued', 'gameplay_command', 'item', 'Treat kind as an item entity, obtain its owner/group, collect eligible handlers, and queue the drop-item order.', runtime+['item ownership and command handlers are runtime state'], 'on_action_shared B1; native command_drop_item_queued literal')
    add([2407219556], 'drop_item', 'gameplay_command', 'item', 'Treat kind as an item entity, obtain its owner/group, collect handlers, and issue the drop-item order.', runtime+['item ownership and command handlers are runtime state'], 'on_action_shared B1; native command_drop_item literal')
    add([1102066046], 'enable_autocast', 'gameplay_command', 'ability', 'Forward through selected units; staged, augment and spawn ability handlers set the matching ability autocast state to true.', runtime, 'StagedAbilityData::on_action; AugmentAbilityData::on_action; SpawnAbilityData::on_action')
    add([1346991488], 'disable_autocast', 'gameplay_command', 'ability', 'Forward through selected units; matching ability handlers clear autocast. Spawn handlers also update AutoSpawnManager.', runtime, 'on_action_shared B54; SpawnAbilityData::on_action B3')
    add([2474515278], 'enable_quick_macro_autocast', 'gameplay_command', 'ability', 'Broadcast to the player units, enable matching spawn autocast, register auto-spawners, and set the player-level flag keyed by data.', runtime, 'on_action_shared B2; SpawnAbilityData::on_action B2')
    add([1735479664], 'disable_quick_macro_autocast', 'gameplay_command', 'ability', 'Broadcast to player units, disable matching spawn autocast, unregister auto-spawners, and clear the player-level flag keyed by data.', runtime, 'on_action_shared B2; SpawnAbilityData::on_action B2')
    add([3534171667], 'acquire_command', 'gameplay_command', 'ability', 'Validate subject and forward to its action handlers; UnitTask routes to acquire_command.', runtime, 'on_action_shared B44; UnitTask::acquire_command')
    add([215225644], 'unload_single_cargo', 'gameplay_command', 'cargo', 'Validate subject and forward to abilities; CargoAbility uses data as the cargo entity to unload.', runtime+['subject must have a matching cargo handler'], 'UnitTask::forward_action_to_abilities; CargoAbility::on_unload_single_cargo')
    add([3703223256], 'cancel_production_queue_item', 'gameplay_command', 'cancel', 'Forward to subject; production handlers remove the queue entry indexed by data with cancellation enabled.', runtime, 'ProductionQueueTask::on_action -> remove_from_queue(index, true)')
    add([117852904], 'clear_destructible_footprint', 'system', 'subject', 'Forward to subject; DestructibleTask clears its footprint grid rectangle when its footprint flag is enabled.', ['subject runtime type/footprint determine whether this handler applies'], 'DestructibleTask::on_action B4 -> _snow_set_footprint_grid(x,y,0)')
    for value, name in [(2402589206,'targeting_started'),(559384890,'targeting_completed'),(2605351170,'targeting_canceled'),(3345376816,'targeting_inactive')]:
        add([value], name, 'targeting', 'ability', 'Decode data as ability plus command index; broadcast targeting state, player slot, subject and location.', ['targeting completion is not proof of ability success'], 'targeting_state_changed_event.h; on_action_shared B27')
    add([580466764], 'update_selection', 'selection', 'none', 'Notify PlayerTask of a changed participant selection.', runtime, 'PlayerTask::update_selection')
    add([3717677309], 'ui_event', 'ui_event', 'ui', 'Broadcast kind as command String ID, data as data String ID, and subject as player.', ['String IDs need the runtime string dictionary for unique text recovery','registered event filters determine behavior'], 'UIEvent::broadcast(String command,String data,u32 player); B10')
    add([1951408186], 'widget_event', 'ui_event', 'widget', 'Broadcast subject widget, participant, kind command String ID, data String ID, and x/y location.', ['widget and string registries','runtime registered callbacks'], 'widgets.h FWidgetEventReceived; B4; table index 2610 registration')
    add([1483826229], 'entity_vm_event', 'ui_event', 'entity_vm', 'Broadcast subject entity, participant, kind command String ID, numeric data, and location to entity VM listeners.', ['entity and command string registries','runtime event filters and callbacks'], 'B52; _GLOBAL__sub_I_main.cpp table index 2605 -> EntityVMEvent__on_entity_vm_event')
    add([417660425], 'player_camera_event', 'camera', 'camera', 'Broadcast participant, location, heading from subject, pitch from kind, and zoom from data after fixed-point conversion.', ['camera listeners may have additional runtime side effects'], 'camera.h FCameraEventReceived; B9')
    add([429833619], 'player_chat_notification', 'notification', 'chat_notification', 'Convert participant to player slot and broadcast data as the chat String ID.', ['runtime string dictionary; separate NetAction.chat may provide matching text'], 'PlayerChatMessageEvent::broadcast')
    add([51725601], 'sequence_custom_event', 'ui_event', 'sequence_custom', 'Broadcast participant player slot, subject sequence-player handle, kind sequence archetype, data event String ID, and location.', ['sequence/player/string runtime registries','registered event filters'], 'Events::SequenceCustomEvent::broadcast')
    for value,name in [(1015585459,'sequence_play'),(2863944085,'sequence_stop'),(3015766174,'sequence_queue_empty')]:
        add([value],name,'notification','sequence','Broadcast sequence playback state with subject sequence-player and kind sequence archetype for the participant player slot.', ['sequence-player runtime registry'], 'Events::SequencePlaybackChanged::broadcast; sequence_playback_changed.h')
    for value,name in [(2155462304,'transmission_play'),(2431388998,'transmission_stop'),(56531927,'transmission_queue_empty')]:
        add([value],name,'notification','transmission','Broadcast transmission playback state with subject player handle and kind archetype for the participant player slot.', ['transmission runtime registry'], 'Events::TransmissionPlaybackChanged::broadcast; transmission_playback_changed.h')
    add([1383849896], 'skip_cinematic', 'ui_event', 'subject', 'Broadcast a skip-cinematic request using subject.', ['registered cinematic/event state'], 'Events::SkipCinematic::broadcast')
    add([3021948337], 'player_ping', 'ping', 'ping', 'Create a player ping from location and configured Ping archetype. kind=99 with nonzero subject instead forwards verb 3306112409 to that subject.', ['ping configuration and target runtime state'], 'on_action_shared B41/B11; Ping::create')
    for value,flag in [(975326616,False),(2966149146,True)]:
        add([value],'spawn_force_location' if flag else 'spawn','system','spawn',f'Call try_spawn_entity(kind,1,subject,location,data,{str(flag).lower()}); the true variant is named spawn_force_location in the native binary.', ['spawn validation/world state'], 'on_action_shared B51/B40 -> try_spawn_entity; native retained names')
    add([2258626040], 'activate_player', 'system', 'player', 'Forward action to the player/entity identified by data.', runtime, 'on_action_shared; activate_player retained symbol')
    add([1911537387], 'create_player_entity', 'system', 'none', 'Call Player::create(participant argument).', runtime, 'on_action_shared B87')
    add([3264454613], 'create_participant_entity', 'system', 'none', 'Acquire an entity and attach the Participant core (3674951886). Return that entity.', runtime, 'on_action_shared B18')
    add([2792379770], 'release_participant_entity', 'system', 'participant_index', 'Resolve the participant entity from data, release it, then reevaluate win conditions.', runtime, 'on_action_shared B17')
    add([2758349417], 'initialize_staging', 'system', 'none', 'Initialize the pending-kill group and assign start locations using MapSettings.', ['map settings and generated map data'], 'init_pending_kill_group; PlayerStartLocationService::assign_player_start_locations')
    add([2847442609], 'start_staging', 'system', 'none', 'Initialize triggers/time of day/music, broadcast the staging event, set staging_started, and cache a save.', ['generated trigger definitions','runtime callbacks'], 'on_action_shared B35/B37')
    add([2954092714], 'start_game', 'system', 'none', 'Store player start locations, create bot players, enable in-game/end-condition flags, evaluate victory, and broadcast a generic game event.', runtime, 'on_action_shared B19/B83')
    add([1037210847], 'cache_save', 'system', 'none', 'Request GameWorld::cache_save.', runtime, 'GameWorld::cache_save')
    add([603245548], 'evaluate_win_condition', 'system', 'none', 'Evaluate the active win condition.', ['map-defined win conditions and current simulation state'], 'GameWorld::evaluate_active_win_condition')
    add([3494620336], 'post_damage_processing', 'system', 'none', 'Run on_post_damages.', ['damage queues and runtime state'], 'on_post_damages')
    add([3926104316], 'set_snowbot_options', 'system', 'bot_options', 'Use data bit 0 to create/bind or unbind/release a Snowbot; bits 1..5 are buildWorkers, maintainSupply, buildStructures, buildArmy, buildExpansion.', ['bot runtime state and option handlers'], 'native 0x1800c9110 case 14; serializer 0x1801857a0; on_action_shared B45')
    lifecycle = {354004291:'on_forfeit_requested',536998780:'on_init_client_requested_pre_staging',1070162333:'on_init_client_requested_post_staging',1365994611:'on_deploy_staged_human',1532564498:'on_disconnected_forever',1755832395:'on_unpause_game',2452358077:'on_disconnected_with_rejoin',2918277820:'on_fulfill_reservation',3271238072:'on_init_reserved',3556953337:'on_rejoined',3741475005:'on_reservation_timeout',3924980620:'on_init_ai_staging',4096938868:'on_pause_game'}
    for value,name in lifecycle.items():
        add([value],name,'system','participant_subject','Construct Participant(subject) and run its matching lifecycle branch, with generated events and state-dependent bookkeeping.', ['participant state and GameWorld flags','runtime event subscribers; no outcome inferred from the name'], f'Participant::handle_action; retained diagnostic string {name}')
    add([4279446118], 'map_player_four_flag', 'system', 'none', 'The exported on_action sets blackboard key 2001821935 to 1 on player slot 4, then calls on_action_shared.', ['original flag name is not recovered','whether the player entity exists is runtime-dependent'], 'exported on_action; _snow_get_player_id(4); _snow_set_blackboard_i32')
    assert len(result) == 66
    return result
