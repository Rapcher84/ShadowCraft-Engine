import gettext
import __builtin__

__builtin__._ = gettext.gettext

from core import exceptions
from calcs import armor_mitigation

class DamageCalculator(object):
    # This method holds the general interface for a damage calculator - the
    # sorts of parameters and calculated values that will be need by many (or
    # most) classes if they implement a damage calculator using this framework.
    # Not saying that will happen, but I want to leave my options open.
    # Any calculations that are specific to a particular class should go in
    # calcs.<class>.<Class>DamageCalculator instead - for an example, see
    # calcs.rogue.RogueDamageCalculator

    # If someone wants to have __init__ take a target level as well and use it
    # to initialize these to a level-dependent value, they're welcome to.  At
    # the moment I'm hardcoding them to level 85 values.
    TARGET_BASE_ARMOR = 11977.
    BASE_ONE_HAND_MISS_RATE = .08
    BASE_DW_MISS_RATE = .27
    BASE_SPELL_MISS_RATE = .17
    BASE_DODGE_CHANCE = .065
    BASE_PARRY_CHANCE = .14
    GLANCE_RATE = .24
    GLANCE_MULTIPLIER = .75

    def __init__(self, stats, talents, glyphs, buffs, race, settings=None, level=85):
        self.stats = stats
        self.talents = talents
        self.glyphs = glyphs
        self.buffs = buffs
        self.race = race
        self.settings = settings
        self.level = level

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        if name == 'level':
            self._set_constants_for_level()

    def __getattr__(self, name):
        # Any status we haven't assigned a value to, we don't have.
        if name == 'calculating_ep':
            return False
        object.__getattribute__(self, name)

    def _set_constants_for_level(self):
        self.buffs.level = self.level
        self.stats.level = self.level
        self.race.level = self.level
        # calculate and cache the level-dependent armor mitigation parameter
        self.armor_mitigation_parameter = armor_mitigation.parameter(self.level)

    def ep_helper(self,stat):
        if stat not in ('dodge_exp', 'white_hit', 'spell_hit', 'yellow_hit', 'parry_exp'):
            setattr(self.stats, stat, getattr(self.stats, stat) + 1.)
        else:
            setattr(self, 'calculating_ep', stat)
        dps = self.get_dps()
        if stat not in ('dodge_exp', 'white_hit', 'spell_hit', 'yellow_hit', 'parry_exp'):
            setattr(self.stats, stat, getattr(self.stats, stat) - 1.)
        else:
            setattr(self, 'calculating_ep', False)

        return dps

    def get_ep(self):
        ep_values = {'white_hit':0, 'spell_hit':0, 'yellow_hit':0,
                     'str':0, 'agi':0, 'haste':0, 'crit':0,
                     'mastery':0, 'dodge_exp':0, 'parry_exp':0}
        baseline_dps = self.get_dps()
        ap_dps = self.ep_helper('ap')
        ap_dps_difference = ap_dps - baseline_dps
        for stat in ep_values.keys():
            dps = self.ep_helper(stat)
            ep_values[stat] = abs(dps - baseline_dps) / ap_dps_difference

        return ep_values

    def get_ranking_for_talents(self, list=None, print_return=False):
        talents_ranking = {}
        not_implemented_talents = []
        baseline_dps = self.get_dps()
        talent_list = []

        if list == None:
        # Build a list of talents that can be taken in the active spec
            for talent in self.talents.treeForTalent.keys():
                if self.talents.__getattr__(talent, tier=True) <= 2:
                    talent_list.append(talent)
                if self.talents.__getattr__(talent, tier=True) > 2 and talent in self.talents.spec.allowed_talents.keys():
                    talent_list.append(talent)
        else:
            talent_list = list

        for talent in talent_list:
            old_talent_value = self.talents.__getattr__(talent)
            if self.talents.__getattr__(talent) == 0:
                new_talent_value = 1
            else:
                new_talent_value = old_talent_value - 1

            for i in (0, 1, 2):
                try:
                    self.talents.trees[i].set_talent(talent, new_talent_value)
                except:
                    pass
            try:
                dps = self.get_dps()
                # Disregard talents that don't affect dps
                if abs(dps - baseline_dps) != 0.0:
                    talents_ranking[talent] = abs(dps - baseline_dps)
            except:
                # These are the talents that the modeler asserts True
                not_implemented_talents.append(talent)
            for i in (0, 1, 2):
                try:
                    self.talents.trees[i].set_talent(talent, old_talent_value)
                except:
                    pass

        if print_return == False:
            return talents_ranking, not_implemented_talents
        else:
            talents_ranking_sorted = talents_ranking.items()
            talents_ranking_sorted.sort(key=lambda entry: entry[1], reverse=True)
            max_len = max(len(entry[0]) for entry in talents_ranking_sorted)
            total_dps = sum(entry[1] for entry in talents_ranking_sorted)
            for entry in talents_ranking_sorted:
                print entry[0] + ':' + ' ' * (max_len - len(entry[0])), entry[1]
            for i in not_implemented_talents:
                print i + ':' + ' ' , _('imperative talent')

    def get_dps(self):
        # Overwrite this function with your calculations/simulations/whatever;
        # this is what callers will (initially) be looking at.
        pass

    def get_spell_hit_from_talents(self):
        # Override this in your subclass to implement talents that modify spell hit chance
        return 0.

    def get_melee_hit_from_talents(self):
        # Override this in your subclass to implement talents that modify melee hit chance
        return 0.

    def get_all_activated_stat_boosts(self):
        racial_boosts = self.race.get_racial_stat_boosts()
        gear_boosts = self.stats.gear_buffs.get_all_activated_boosts()
        return racial_boosts + gear_boosts

    def armor_mitigation_multiplier(self, armor):
        return armor_mitigation.multiplier(armor, cached_parameter=self.armor_mitigation_parameter)

    def armor_mitigate(self, damage, armor):
        # Pass in raw physical damage and armor value, get armor-mitigated
        # damage value.
        return damage * self.armor_mitigation_multiplier(armor)

    def melee_hit_chance(self, base_miss_chance, dodgeable, parryable, weapon_type):
        hit_chance = self.stats.get_melee_hit_from_rating() + self.race.get_racial_hit() + self.get_melee_hit_from_talents()
        miss_chance = max(base_miss_chance - hit_chance,0)

        #Expertise represented as the reduced chance to be dodged or parried, not true "Expertise"
        expertise = self.stats.get_expertise_from_rating() + self.race.get_racial_expertise(weapon_type)

        if dodgeable:
            dodge_chance = max(self.BASE_DODGE_CHANCE - expertise, 0)
            if self.calculating_ep == 'dodge_exp':
                dodge_chance += self.stats.get_expertise_from_rating(1)
        else:
            dodge_chance = 0

        if parryable:
            parry_chance = max(self.BASE_PARRY_CHANCE - expertise, 0)
            if self.calculating_ep in ('parry_exp', 'dodge_exp'):
                parry_chance += self.stats.get_expertise_from_rating(1)
        else:
            parry_chance = 0

        return 1 - (miss_chance + dodge_chance + parry_chance)

    def one_hand_melee_hit_chance(self, dodgeable=True, parryable=False, weapon=None):
        # Most attacks by DPS aren't parryable due to positional negation. But
        # if you ever want to attacking from the front, you can just set that
        # to True.
        if weapon == None:
            weapon = self.stats.mh
        hit_chance = self.melee_hit_chance(self.BASE_ONE_HAND_MISS_RATE, dodgeable, parryable, weapon.type)
        if self.calculating_ep == 'yellow_hit':
            hit_chance -= self.stats.get_melee_hit_from_rating(1)
        return hit_chance

    def off_hand_melee_hit_chance(self, dodgeable=True, parryable=False, weapon=None):
        # Most attacks by DPS aren't parryable due to positional negation. But
        # if you ever want to attacking from the front, you can just set that
        # to True.
        if weapon == None:
            weapon = self.stats.oh
        hit_chance = self.melee_hit_chance(self.BASE_ONE_HAND_MISS_RATE, dodgeable, parryable, weapon.type)
        if self.calculating_ep == 'yellow_hit':
            hit_chance -= self.stats.get_melee_hit_from_rating(1)
        return hit_chance

    def dual_wield_mh_hit_chance(self, dodgeable=True, parryable=False):
        # Most attacks by DPS aren't parryable due to positional negation. But
        # if you ever want to attacking from the front, you can just set that
        # to True.
        return self.dual_wield_hit_chance(dodgeable, parryable, self.stats.mh.type)

    def dual_wield_oh_hit_chance(self, dodgeable=True, parryable=False):
        # Most attacks by DPS aren't parryable due to positional negation. But
        # if you ever want to attacking from the front, you can just set that
        # to True.
        return self.dual_wield_hit_chance(dodgeable, parryable, self.stats.oh.type)

    def dual_wield_hit_chance(self, dodgeable, parryable, weapon_type):
        hit_chance = self.melee_hit_chance(self.BASE_DW_MISS_RATE, dodgeable, parryable, weapon_type)
        if self.calculating_ep in ('yellow_hit','spell_hit','white_hit'):
            hit_chance -= self.stats.get_melee_hit_from_rating(1)
        return hit_chance

    def spell_hit_chance(self):
        hit_chance = 1 - max(self.BASE_SPELL_MISS_RATE - self.stats.get_spell_hit_from_rating() - self.get_spell_hit_from_talents() - self.race.get_racial_hit(), 0)
        if self.calculating_ep in ('yellow_hit', 'spell_hit'):
            hit_chance -= self.stats.get_spell_hit_from_rating(1)
        return hit_chance

    def buff_melee_crit(self):
        return self.buffs.buff_all_crit()

    def buff_spell_crit(self):
        return self.buffs.buff_spell_crit() + self.buffs.buff_all_crit()

    def target_armor(self, armor=None):
        # Passes base armor reduced by armor debuffs or overridden armor
        if armor is None:
            armor = self.TARGET_BASE_ARMOR
        return self.buffs.armor_reduction_multiplier() * armor

    def raid_settings_modifiers(self, is_spell=False, is_physical=False, is_bleed=False, armor=None):
        # This function wraps spell, bleed and physical debuffs from raid
        # along with all-damage buff and armor reduction. It should be called
        # from every damage dealing formula. Armor can be overridden if needed.
        if is_spell + is_bleed + is_physical != 1:
            raise exceptions.InvalidInputException(_('Attacks cannot benefit from more than one type of raid damage multiplier'))
        armor_override = self.target_armor(armor)
        if is_spell:
            return self.buffs.spell_damage_multiplier()
        elif is_bleed:
            return self.buffs.bleed_damage_multiplier()
        elif is_physical:
            return self.buffs.physical_damage_multiplier() * self.armor_mitigation_multiplier(armor_override)
