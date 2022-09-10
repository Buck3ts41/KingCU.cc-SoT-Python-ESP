import threading
from threading import *
import struct
import logging
from memory_helper import ReadMemory
from mapping import ship_keys
from mapping import entity_keys
from mapping import chest_keys
from mapping import prj_keys
from mapping import event_keys
from mapping import crates_keys
from helpers import OFFSETS, CONFIG, logger
from Modules.ship import Ship
from Modules.crews import Crews
from Modules.entity import Entity
from Modules.chest import Chest
from Modules.event import Event
from Modules.projectile import Prj
from Modules.crates import Crates


class SoTMemoryReader:


    def __init__(self):

        self.rm = ReadMemory("SoTGame.exe")
        base_address = self.rm.base_address
        logging.info(f"Process ID: {self.rm.pid}")

        u_world_offset = self.rm.read_ulong(
            base_address + self.rm.u_world_base + 3
        )
        u_world = base_address + self.rm.u_world_base + u_world_offset + 7
        self.world_address = self.rm.read_ptr(u_world)

        g_name_offset = self.rm.read_ulong(
            base_address + self.rm.g_name_base + 3
        )
        g_name = base_address + self.rm.g_name_base + g_name_offset + 7
        logging.info(f"SoT gName Address: {hex(g_name)}")
        self.g_name = self.rm.read_ptr(g_name)

        g_objects_offset = self.rm.read_ulong(
            base_address + self.rm.g_object_base + 2
        )
        g_objects = base_address + self.rm.g_object_base + g_objects_offset + 22
        logging.info(f"SoT gObject Address: {hex(g_objects)}")
        self.g_objects = self.rm.read_ptr(g_objects)

        self.u_level = self.rm.read_ptr(self.world_address +
                                        OFFSETS.get('World.PersistentLevel'))

        self.u_local_player = self._load_local_player()
        self.player_controller = self.rm.read_ptr(
            self.u_local_player + OFFSETS.get('LocalPlayer.PlayerController')
        )

        self.my_coords = self._coord_builder(self.u_local_player)
        self.my_coords['fov'] = 90

        self.actor_name_map = {}
        self.server_players = []
        self.display_objects = []
        self.crew_data = None


    def _load_local_player(self) -> int:
        """
        Returns the local player object out of uWorld.UGameInstance.
        Used to get the players coordinates before reading any actors
        :rtype: int
        :return: Memory address of the local player object
        """
        game_instance = self.rm.read_ptr(
            self.world_address + OFFSETS.get('World.OwningGameInstance')
        )
        local_player = self.rm.read_ptr(
            game_instance + OFFSETS.get('GameInstance.LocalPlayers')
        )
        return self.rm.read_ptr(local_player)

    def update_my_coords(self):
        """
        Function to update the players coordinates and camera information
        storing that new info back into the my_coords field. Necessary as
        we dont always run a full scan and we need a way to update ourselves
        """
        manager = self.rm.read_ptr(
            self.player_controller + OFFSETS.get('PlayerController.CameraManager')
        )
        self.my_coords = self._coord_builder(
            manager,
            OFFSETS.get('PlayerCameraManager.CameraCache')
            + OFFSETS.get('CameraCacheEntry.MinimalViewInfo'),
            fov=True)

    def _coord_builder(self, actor_address: int, offset=0x78, camera=True,
                       fov=False) -> dict:
        """
        Given a specific actor, loads the coordinates for that actor given
        a number of parameters to define the output
        :param int actor_address: Actors base memory address
        :param int offset: Offset from actor address to beginning of coords
        :param bool camera: If you want the camera info as well
        :param bool fov: If you want the FoV info as well
        :rtype: dict
        :return: A dictionary containing the coordinate information
        for a specific actor
        """
        if fov:
            actor_bytes = self.rm.read_bytes(actor_address + offset, 44)
            unpacked = struct.unpack("<ffffff16pf", actor_bytes)
        else:
            actor_bytes = self.rm.read_bytes(actor_address + offset, 24)
            unpacked = struct.unpack("<ffffff", actor_bytes)

        coordinate_dict = {"x": unpacked[0]/100, "y": unpacked[1]/100,
                           "z": unpacked[2]/100}
        if camera:
            coordinate_dict["cam_x"] = unpacked[3]
            coordinate_dict["cam_y"] = unpacked[4]
            coordinate_dict["cam_z"] = unpacked[5]
        if fov:
            coordinate_dict['fov'] = unpacked[7]

        return coordinate_dict

    def read_actors(self):
        """
        Represents a full scan of every actor within our render distance.
        Will create an object for each type of object we are interested in,
        and store it in a class variable (display_objects).
        Then our main game loop updates those objects
        """
        # On a full run, start by cleaning up all the existing text renders
        for display_ob in self.display_objects:
            try:
                display_ob.text_render.delete()
            except:
                continue
            try:
                display_ob.icon.delete()
            except:
                continue
        self.display_objects = []
        self.update_my_coords()

        actor_raw = self.rm.read_bytes(self.u_level + 0xa0, 0xC)
        actor_data = struct.unpack("<Qi", actor_raw)

        self.server_players = []
        for x in range(0, actor_data[1]):
            # We start by getting the ActorID for a given actor, and comparing
            # that ID to a list of "known" id's we cache in self.actor_name_map
            raw_name = ""
            actor_address = self.rm.read_ptr(actor_data[0] + (x * 0x8))
            actor_id = self.rm.read_int(
                actor_address + OFFSETS.get('Actor.actorId')
            )

            # We save a mapping of actor id to actor name for the sake of
            # saving memory calls
            if actor_id not in self.actor_name_map and actor_id != 0:
                try:
                    raw_name = self.rm.read_gname(actor_id)
                    self.actor_name_map[actor_id] = raw_name
                except Exception as e:
                    logger.error(f"Unable to find actor name: {e}")
            elif actor_id in self.actor_name_map:
                raw_name = self.actor_name_map.get(actor_id)


            if not raw_name:
                continue

            def shipESP():

                self.display_objects.append(ship)

            def entityESP():
                self.display_objects.append(entity)

            def eventESP():
                self.display_objects.append(event)

            def cratesESP():
                self.display_objects.append(crates)

            def prjESP():
                self.display_objects.append(prj)

            def chestESP():
                self.display_objects.append(chest)

            def crew():
                self.crew_data = Crews(self.rm, actor_id, actor_address)




            if CONFIG.get('SHIPS_ENABLED') and raw_name in ship_keys:
                ship = Ship(self.rm, actor_id, actor_address, self.my_coords,
                            raw_name)
                t1 = Thread(target=shipESP)
                t1.start()


            if CONFIG.get('ENTITY_ENABLED') and raw_name in entity_keys:
                entity = Entity(self.rm, actor_id, actor_address, self.my_coords,
                            raw_name)
                t2 = Thread(target=entityESP)
                t2.start()

            if CONFIG.get('EVENT_ENABLED') and raw_name in event_keys:
                event = Event(self.rm, actor_id, actor_address, self.my_coords,
                            raw_name)
                t3 = Thread(target=eventESP)
                t3.start()

            if CONFIG.get('CRATES_ENABLED') and raw_name in crates_keys:
                crates = Crates(self.rm, actor_id, actor_address, self.my_coords,
                            raw_name)

                t4 = Thread(target=cratesESP)
                t4.start()

            if CONFIG.get('PRJ_ENABLED') and raw_name in prj_keys:
                prj = Prj(self.rm, actor_id, actor_address, self.my_coords,
                            raw_name)

                t5 = Thread(target=prjESP)
                t5.start()

            if CONFIG.get('CHEST_ENABLED') and raw_name in chest_keys:
                chest = Chest(self.rm, actor_id, actor_address, self.my_coords,
                            raw_name)

                t6 = Thread(target=chestESP)
                t6.start()
            if CONFIG.get('CREWS_ENABLED') and raw_name == "CrewService":
                t7 = Thread(target=crew)
                t7.start()




























